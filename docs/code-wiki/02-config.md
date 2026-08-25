# 02 · 配置系统

配置是文译所有模块的单一来源。配置文件是 `config.yaml`（首次运行 CLI 时由 `Config.create_default_file` 原子创建），加载后转为 pydantic v2 模型供全代码使用。

## 文件：`trans_novel/config.py`

### 配置模型层次

```python
Config
├── source_lang: str = "auto"        # auto | ja | en | ko | ru | de | fr | es | it | pt
├── target_lang: str = "zh"
├── llm: LLMConfig
│   ├── provider: str = "deepseek"   # deepseek|openai|openrouter|openai-compatible|ollama|vllm|fake
│   ├── base_url: str | None
│   ├── api_key_env: str | None      # 环境变量名（不直接存密钥）
│   ├── reasoning_style: Literal["none","deepseek","openai","openrouter"] = "none"
│   ├── timeout: int = 600
│   ├── max_retries: int = 4
│   └── tiers: dict[str, TierConfig] # {"strong":..., "cheap":..., "fast":...}
│       └── TierConfig { model: str|None, options: dict[str, Any] }
├── segment: SegmentConfig
│   ├── max_chars_per_batch: int = 1800   # 翻译批次目标大小
│   └── max_chars_per_segment: int = 1200 # 单段超长则按句再切
├── pipeline: PipelineConfig
│   ├── review: bool = True                  # 章末审校
│   ├── autofix_severe: bool = False         # 审校后自动重译漏译/误译
│   ├── align_retry_limit: int = 2           # 批次段数不符重试次数
│   ├── polish: bool = True                  # 强档润色（最贵）
│   ├── backtranslate_sample: float = 0.0    # 回译抽检比例（0 关闭）
│   ├── consistency_qa: bool = False         # 全书跨章一致性扫描
│   ├── rolling_context_segments: int = 6    # 注入的前文译文尾段数
│   ├── book_understanding: bool = True      # 翻译前预扫生成全书概览
│   ├── prescan_concurrency: int = 4         # 预扫并发数
│   ├── review_concurrency: int = 4          # 章末审校并发数
│   └── glossary_scope: str = "chapter"      # chapter=本章命中；full=全量表
├── output: OutputConfig
│   ├── mono: bool = True                    # 产出单语中文版
│   ├── bilingual: bool = False              # 产出双语对照版
│   ├── bilingual_order: str = "target_first" # target_first | source_first
│   └── about_page: bool = True              # 书末附"关于此翻译"页
├── honorific_strategy: str = "keep_style"   # keep_style | normalize | drop
├── punctuation_normalize: bool = True
└── state_dir: str = "state"
```

### 关键类与方法

#### `Config`

```python
@staticmethod
def create_default_file(path: str) -> bool
```
在 `path` 不存在时用 `open("x")` 原子创建默认配置；已存在则返回 False，绝不覆盖用户配置。CLI 在 Click 解析前就会调用它（见 `cli.py:_ConfigInitializingGroup`），确保 `--help` 等早退命令也初始化配置。

```python
@classmethod
def load(cls, path: str = "config.yaml") -> "Config"
```
读取 YAML 并 `from_dict` 解析。

```python
@classmethod
def from_dict(cls, raw: dict[str, Any]) -> "Config"
```
把 YAML 的 `language` / `llm` / `segment` / `pipeline` / `output` / `honorific` / `punctuation` / `paths` 各节映射到扁平字段（如 `raw["language"]["source"]` → `Config.source_lang`）。`TierConfig` 用 `model_validate` 校验，`extra="forbid"` 拒绝未知字段。

### `TierConfig`

```python
class TierConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)
```
跨 provider 通用的档位覆盖。`options` 是 provider 专属参数（如 DeepSeek 的 `thinking` / `reasoning_effort`），由各 provider 用自己的 `OptionsT` pydantic 模型 `model_validate` 校验。详见 [04-llm.md](04-llm.md)。

### `ReasoningStyle`

```python
ReasoningStyle = Literal["none", "deepseek", "openai", "openrouter"]
```
仅 `openai-compatible` provider 使用，决定思考参数的方言协议。其他 provider 各自有固定方言。

## 配置文件示例

默认生成的 `config.yaml`（节选）：

```yaml
language:
  source: auto
  target: zh

llm:
  provider: deepseek
  base_url: https://api.deepseek.com
  api_key_env: DEEPSEEK_API_KEY
  timeout: 600
  max_retries: 4
  tiers:
    strong:
      model: deepseek-v4-pro
      options:
        thinking: true
        reasoning_effort: high
    cheap:
      model: deepseek-v4-flash
      options:
        thinking: true
        reasoning_effort: high
    fast:
      model: deepseek-v4-flash
      options:
        thinking: false

segment:
  max_chars_per_batch: 1800
  max_chars_per_segment: 1200

pipeline:
  review: true
  autofix_severe: false
  align_retry_limit: 2
  polish: true
  backtranslate_sample: 0
  consistency_qa: false
  rolling_context_segments: 6
  book_understanding: true
  prescan_concurrency: 4
  review_concurrency: 4
  glossary_scope: chapter

output:
  mono: true
  bilingual: false
  bilingual_order: target_first
  about_page: true
```

## CLI 与 Web UI 的配置流

### CLI 路径

`cli.py` 的 `_ConfigInitializingGroup` 在 Click 分派前从 `sys.argv` 提取 `--config`/`-c`（`_config_path_from_args`），调用 `Config.create_default_file`，再用 `Config.load(path)` 读取。所有命令通过 `_load_config()` 拿到 `Config` 实例。

### Web UI 路径

Web UI 不直接读 `config.yaml`，而是：
1. 前端 `SettingsSheet` 编辑 `WebSettings`（pydantic 模型，字段更贴近 UI）。
2. `PUT /api/settings` 保存到 `~/.wenyi-webui/settings.json`。
3. 启动任务时 `TaskManager._write_config` 把 `WebSettings` dump 成 worker 用的 `config.yaml`（写到任务专属目录）。
4. worker 子进程 `Config.load(config_path)` 读取该配置。

因此 Web UI 的每个任务都有独立的配置快照，与 CLI 的全局 `config.yaml` 互不影响。

## 运行期配置修改

`Orchestrator._apply_language(lang)` 会在 `source_lang=auto` 检测完成后写回 `config.source_lang` 并同步到所有 7 个 agent 的 `.src` 属性。除此之外，配置在运行期是只读的。

CLI 命令行参数（`--polish/--no-polish`、`--qa/--no-qa`、`--mono/--no-mono`、`--bilingual/--no-bilingual`）会覆盖配置文件中的对应字段，仅对本次运行生效，不写回 `config.yaml`。
