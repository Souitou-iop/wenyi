# 04 · LLM Provider 抽象层（llm）

`llm` 模块是所有 LLM 调用的稳定抽象层。它定义统一接口、按 provider 字符串工厂化创建实例、处理多服务商方言、跟踪 token 用量。**业务回退（默认值）不在这里**，而在 `agents/base.py:Agent._ask_json`。

## 模块结构

```
llm/
├── __init__.py              # 导出 LLMClient, Messages, build_client, parse_json_loose, FakeClient
├── base.py                  # LLMClient 抽象基类 + complete_json 模板方法
├── factory.py               # build_client(config) 工厂
├── json_parser.py           # parse_json_loose 宽松 JSON 解析
├── tiers.py                 # resolve_tier 档位回退规则
├── usage.py                 # UsageTracker + UsageSample + 增量合并
└── providers/
    ├── __init__.py
    ├── _openai_compatible.py  # OpenAICompatibleBaseClient 基类（传输/重试/档位/JSON/usage）
    ├── deepseek.py            # DeepSeekClient（默认三档）
    ├── openai.py              # OpenAIClient
    ├── openrouter.py          # OpenRouterClient
    ├── openai_compatible.py   # OpenAICompatibleClient（通用兼容，4 种 reasoning_style）
    ├── ollama.py              # OllamaClient（薄子类）
    ├── vllm.py                # VLLMClient（薄子类）
    └── fake.py                # FakeClient（测试用）
```

## 文件：`llm/base.py` — 抽象接口

```python
Messages = list[dict[str, str]]  # OpenAI 风格对话消息

class LLMClient(ABC):
    def __init__(self) -> None:
        self.usage = UsageTracker()

    def usage_summary(self) -> dict[str, Any]
        # 代理到 self.usage.summary()，返回 {totals, by_tier, by_stage, cache_hit_rate}

    @abstractmethod
    def complete(self, messages: Messages, *,
                 tier: str = "strong",
                 json_mode: bool = False,
                 max_tokens: Optional[int] = None,
                 stage: Optional[str] = None) -> str
        # 返回模型回复纯文本；stage 仅用于用量归因

    def complete_json(self, messages, *,
                      tier="strong", max_tokens=None, stage=None) -> Any
        # 模板方法：先 complete(json_mode=True)，再 parse_json_loose 解析
```

`stage` 是用量归因维度（如 `"language_detect"` / `"translate"` / `"review"` / `"title_translate"` / Agent 类名），与 `tier`（模型档位）正交。

## 文件：`llm/factory.py` — 工厂

```python
def build_client(config: Config) -> LLMClient
```

按 `config.llm.provider` 字符串（标准化为小写、`_` → `-`）匹配 7 个 provider，**懒加载**（每个 provider 在匹配处才 `import`，避免导入期就拉起 `openai` SDK）：

| provider 字符串 | 类 | 备注 |
|----------------|----|----|
| `deepseek` | `DeepSeekClient` | 默认三档：v4-pro / v4-flash / v4-flash |
| `openai` | `OpenAIClient` | 无默认档，用户必配 `strong` |
| `openrouter` | `OpenRouterClient` | 无默认档 |
| `openai-compatible` / `custom` | `OpenAICompatibleClient` | 通用兼容，4 种 `reasoning_style` |
| `ollama` | `OllamaClient` | 本地 `localhost:11434/v1`，无 api key |
| `vllm` | `VLLMClient` | 本地 `localhost:8000/v1`，无 api key |
| `fake` | `FakeClient` | 测试用，不调 API |

未知 provider 抛 `ValueError`。

## 文件：`llm/json_parser.py` — 宽松 JSON 解析

模型输出经常不是严格 JSON（带代码围栏、前后多余文本、字符串内未转义引号等）。`parse_json_loose` 逐级兜底：

1. 直接 `json.loads(text.strip())`
2. 剥离 ```` ```json ... ``` ```` 代码围栏后再 `json.loads`
3. 截取首个 `[...]` 或 `{...}` 块
4. 用 `JSONDecoder().raw_decode` 从首个 `{`/`[` 起解析首个完整 JSON 值，忽略尾部多余字符
5. 调 `_repair_unescaped_quotes` 后再 `raw_decode`（启发式：字符串内 `"` 后若不是 `,:]}` 或空白后跟这些字符，视为内容引号转义为 `\"`，专为中文译文设计）
6. 修复后对完整文本与各对象/数组片段逐一尝试 `json.loads`
7. 全部失败 → 抛 `ValueError`，附前 200 字符上下文

## 文件：`llm/tiers.py` — 档位回退

```python
_TIER_FALLBACK = {
    "fast":  ("cheap", "strong"),
    "cheap": ("strong",),
    "strong": (),  # 不回退，缺则 KeyError
}
```

**原则：永远向更便宜的方向回退**，绝不因缺档反而升到更贵的档。

```python
def resolve_tier(tiers: dict[str, TierConfigT], tier: str) -> TierConfigT
```
tier 命中即返回；否则按 `_TIER_FALLBACK` 顺序查；最终回退到 `tiers["strong"]`。

tiers.py 本身不定义档位内容，只定义回退规则。档位内容由 provider 默认值（仅 DeepSeek 提供）+ 用户 `Config.llm.tiers` 覆盖，经 `resolve_provider_tiers` 合并。

## 文件：`llm/usage.py` — 用量跟踪

### 核心数据结构

```python
_USAGE_FIELDS = ("calls", "prompt_tokens", "completion_tokens",
                 "total_tokens", "cache_hit_tokens", "cache_miss_tokens")

@dataclass(frozen=True)
class UsageSample:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
```

### `UsageTracker` — 线程安全累计器

```python
class UsageTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self._by_tier = {}   # 按模型档位
        self._by_stage = {}  # 按调用阶段

    def record(self, tier: str, sample: UsageSample | None, stage: str | None = None) -> None
        # 锁内同时累加 tier 槽和（若有）stage 槽

    def summary(self) -> dict[str, Any]
        # 返回 {totals, by_tier, by_stage}，每槽补 cache_hit_rate
```

**双层归因**：同一次调用同时进 `_by_tier` 和 `_by_stage` 两张表。`totals` **只由 by_tier 累加**（避免与 by_stage 重复）。

### Provider 归一化

不同 provider 的 usage 字段位置不同：

- **OpenAI 风格**（`normalize_openai_usage`）：读嵌套 `prompt_tokens_details.cached_tokens`，`cache_hit = cached`，`cache_miss = max(0, prompt - cached)`。
- **DeepSeek**（`normalize_deepseek_usage`）：读顶层 `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`。

`make_usage_sample(usage, *, cache_hit_tokens=0, cache_miss_tokens=0)` 把各 API 共用字段标准化为 provider 无关的 `UsageSample`。

### 增量落盘机制

`Orchestrator` 持有 `_usage_checkpoint = self.client.usage_summary()`（上次落盘快照）。每次 `_flush_usage(store, scope)`：

1. `current = client.usage_summary()`（进程内累计）
2. `increment = usage_delta(current, checkpoint)`（非负增量，`max(0, cur - old)`，全 0 的槽丢弃）
3. `checkpoint = current`
4. `accumulated = store.load_usage() or 空 summary`
5. `cumulative = merge_usage_summaries(accumulated, increment)`
6. `store.save_usage(cumulative)` + `log_event("usage_summary", scope, increment, cumulative)`

这样跨 run 续跑时不会重复计费。`usage_delta` 用非负差值防止 checkpoint 与落盘不一致导致负数。

关键函数：`read_usage_int(usage, name)`、`_hit_rate(hit, miss)`、`_normalize_usage_group(group)`、`_usage_group_delta(current, previous)`、`_merge_usage_groups(*groups)`、`usage_delta(current, previous)`、`merge_usage_summaries(accumulated, increment)`。

## Provider 层次结构

```
LLMClient (ABC, base.py)
├── FakeClient                                  # 离线/测试，不依赖 SDK
└── OpenAICompatibleBaseClient[OptionsT]        # _openai_compatible.py
    │   (Generic, 持有 openai.OpenAI 实例、tenacity 重试、档位解析、JSON 模式注入、usage 归一化)
    ├── DeepSeekClient       [DeepSeekTierOptions]
    ├── OpenAIClient         [OpenAITierOptions]
    ├── OpenRouterClient     [OpenRouterTierOptions]
    └── OpenAICompatibleClient [OpenAICompatibleTierOptions]   # 4 种 reasoning_style
        ├── OllamaClient     # localhost:11434/v1, 无 api key
        └── VLLMClient       # localhost:8000/v1, 无 api key
```

## 文件：`llm/providers/_openai_compatible.py` — 共用基类

所有 OpenAI Chat Completions 兼容 provider 的基类与工具。

### `ResolvedTier`

```python
@dataclass(frozen=True)
class ResolvedTier(Generic[OptionsT]):
    model: str
    options: OptionsT  # provider 专属 pydantic 模型
```

### 关键函数

```python
def resolve_provider_tiers(overrides: dict[str, TierConfig], *,
                           options_type, defaults=None) -> dict[str, ResolvedTier]
```
合并通用 `TierConfig` 覆盖与 provider 内置默认；用 provider 专属 options 模型 `model_validate` 校验；**强制要求 `strong` 存在**。

```python
def base_request_kwargs(model, messages, *, json_mode) -> dict
```
组装所有兼容端点共用的请求体 `{model, messages, stream: False}`。`json_mode=True` 时给 system 消息追加 `"Output must be valid json."`，并设 `response_format={"type": "json_object"}`。

```python
def deep_merge(base, override) -> dict
```
递归合并 provider 请求体，用户值优先。

```python
def normalize_openai_usage(usage) -> UsageSample | None
```
把 OpenAI 嵌套的 `prompt_tokens_details.cached_tokens` 转成统一 `UsageSample`。

### `OpenAICompatibleBaseClient`

```python
class OpenAICompatibleBaseClient(LLMClient, Generic[OptionsT]):
    def __init__(self, cfg: LLMConfig, *, provider_name, default_base_url,
                 default_api_key_env, tiers: dict[str, ResolvedTier], requires_api_key)
    def _ensure_client(self) -> Any                   # 懒加载 openai.OpenAI，校验 env api key
    def _normalize_usage(self, usage) -> UsageSample | None  # 默认调 normalize_openai_usage
    @abstractmethod
    def _build_request_kwargs(self, tier_config, messages, *, json_mode, max_tokens) -> dict
    def complete(self, messages, *, tier="strong", json_mode=False, max_tokens=None, stage=None) -> str
```

`complete` 流程：
1. `resolve_tier(self.tiers, tier)` 取 `ResolvedTier`（缺档自动回退）。
2. 子类的 `_build_request_kwargs` 生成 provider 方言的请求体。
3. `_ensure_client()` 懒加载并校验 OpenAI SDK 与 API key（线程安全，单实例）。
4. `tenacity` 重试装饰器：`stop_after_attempt(cfg.max_retries + 1)`、`wait_exponential(multiplier=1, max=30)`、对所有异常重试、`reraise=True`。
5. 调用 `client.chat.completions.create(**kwargs)`，归一化 usage 后 `self.usage.record(tier, sample, stage)`，返回 `response.choices[0].message.content or ""`。

## 各 Provider 详情

### DeepSeek（`providers/deepseek.py`）

- `DEFAULT_BASE_URL = "https://api.deepseek.com"`
- `DEFAULT_API_KEY_ENV = "DEEPSEEK_API_KEY"`
- `DeepSeekTierOptions`: `thinking: bool = True`、`reasoning_effort: str = "high"`、`extra_body: dict`
- 默认三档：
  - `strong` → `deepseek-v4-pro`，thinking=True
  - `cheap` → `deepseek-v4-flash`，thinking=True
  - `fast` → `deepseek-v4-flash`，thinking=False
- `build_request_kwargs`：`extra_body["thinking"] = {"type": "enabled"/"disabled"}`；thinking 启用时设 `kwargs["reasoning_effort"]`；thinking 时强制 `max(max_tokens, 4096)`。
- 覆写 `_normalize_usage` 走 DeepSeek 顶层缓存字段。

### OpenAI（`providers/openai.py`）

- `DEFAULT_BASE_URL = "https://api.openai.com/v1"`
- `DEFAULT_API_KEY_ENV = "OPENAI_API_KEY"`
- `OpenAITierOptions`: `thinking`、`reasoning_effort`、`extra_body`
- **无默认档**，用户必须显式配置 `strong`。
- `build_request_kwargs`：`kwargs["reasoning_effort"] = options.reasoning_effort if thinking else "none"`；用 `max_completion_tokens` 字段（OpenAI 新接口）。

### OpenRouter（`providers/openrouter.py`）

- `DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"`
- `DEFAULT_API_KEY_ENV = "OPENROUTER_API_KEY"`
- 用 `extra_body["reasoning"] = {"effort": ...}` 或 `{"enabled": False}` 表达思考开关。
- 无默认档。

### OpenAI-Compatible（`providers/openai_compatible.py`）

通用兼容端点，支持 4 种 `reasoning_style`：

| `reasoning_style` | 思考参数方言 |
|-------------------|-------------|
| `"deepseek"` | `extra_body["thinking"] = {"type": "enabled"/"disabled"}` |
| `"openai"` | `kwargs["reasoning_effort"] = effort` / `"none"` |
| `"openrouter"` | `extra_body["reasoning"] = {"effort": ...}` / `{"enabled": False}` |
| `"none"` | 不加思考参数 |

`OpenAICompatibleTierOptions`: `thinking: bool = False`（默认关）、`reasoning_effort: str = "high"`、`request_overrides: dict`（未知字段透传到请求体）。

### Ollama / vLLM（薄子类）

- `OllamaClient`：`default_base_url="http://localhost:11434/v1"`，`requires_api_key=False`。
- `VLLMClient`：`default_base_url="http://localhost:8000/v1"`，`requires_api_key=False`。
- 其余复用 `OpenAICompatibleClient`。

### Fake（`providers/fake.py`）

```python
class FakeClient(LLMClient):
    def __init__(self, handler: Optional[Callable[[Messages, str, bool], str]] = None)
    def complete(self, messages, *, tier="strong", json_mode=False, max_tokens=None, stage=None) -> str
```

- `handler(messages, tier, json_mode) -> str`：用户注入的伪响应函数。
- `self.calls: list[dict[str, Any]]`：记录每次调用的入参，便于测试断言。
- 默认行为：`json_mode` 返回 `"[]"`，否则返回空串。

详见 [12-testing.md](12-testing.md)。

## 添加新 Provider 的步骤

1. 在 `llm/providers/` 下新建 `<name>.py`。
2. 定义 `<Name>TierOptions(BaseModel)`（`extra="forbid"`），包含 provider 专属参数。
3. 定义 `_default_tiers()`（可选，若提供默认档位）。
4. 定义 `build_request_kwargs(tier_config, messages, *, json_mode, max_tokens) -> dict`，调 `base_request_kwargs` 拿基础请求体再加方言。
5. 定义 `<Name>Client(OpenAICompatibleBaseClient[<Name>TierOptions])`，在 `__init__` 调 `resolve_provider_tiers`，覆写 `_build_request_kwargs`（必要时覆写 `_normalize_usage`）。
6. 在 `llm/factory.py:build_client` 加一个 `if provider == "<name>":` 分支。
7. 若 provider 有新的缓存字段格式，在 `usage.py` 加归一化函数并在 `_normalize_usage` 调用。
