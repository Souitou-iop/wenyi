# 12 · 测试体系

文译的测试以 pytest 为主，覆盖后端各模块。前端用 vitest + testing-library。所有 LLM 调用通过 `FakeClient` 离线进行，不依赖真实 API。

## 后端测试

### 运行

```bash
uv run pytest                         # 全部测试
uv run pytest tests/test_translator.py   # 单个文件
uv run pytest -k translator              # 按名称筛选
```

### 测试文件一览

| 文件 | 覆盖范围 |
|------|----------|
| `tests/test_app_worker.py` | Web worker 子进程协议（EventWriter / run_worker） |
| `tests/test_assemble.py` | EPUB/TXT 回填组装 |
| `tests/test_bilingual.py` | 双语版输出 |
| `tests/test_book_inspector.py` | 图书元数据提取 |
| `tests/test_cli.py` | CLI 命令端到端 |
| `tests/test_config.py` | 配置加载与默认值 |
| `tests/test_glossary.py` | 术语库 SQLite 持久化 |
| `tests/test_glossary_agents.py` | 术语抽取 Agent |
| `tests/test_ingest.py` | EPUB/FB2/TXT 解析与切分 |
| `tests/test_llm.py` | LLM Provider 抽象层 |
| `tests/test_newfeatures.py` | 新特性回归 |
| `tests/test_orchestrator.py` | 流水线编排 |
| `tests/test_review_polish.py` | 审校与润色 |
| `tests/test_translator.py` | 翻译器段对齐 |
| `tests/test_usage.py` | token 用量跟踪 |
| `tests/test_web.py` | Web API 端点 |

### 辅助文件

#### `tests/fake_llm.py` — FakeClient handler

按 agent 类型路由的 `FakeClient` handler，驱动整条流水线（离线）。核心是 `routing_handler(messages, tier, json_mode)`：

- 通过 `messages[0]["content"]`（system prompt）里的关键词识别当前 agent 类型。
- 用 `_count_numbered(user)` 数 user 里的 `[N]` 编号项，返回等长数组保证段对齐。
- 返回固定 JSON 或文本：

| system 关键词 | 返回 |
|--------------|------|
| `"语言识别器"` | `{"language": "ja"}` |
| `"前期分析师"` | `{"genre":"校园","tone":"冷峻","style_guide":"克制","characters":[...],"terms":[]}` |
| `"标题翻译"` | `{"titles": ["标题0", ...]}`（按编号数） |
| `"文学翻译"` | `{"translations": ["译0", ...]}`（按编号数） |
| `"中文润色编辑"` | `{"polished": ["润0", ...]}`（按编号数） |
| `"译文审校"` | `{"issues": []}` |
| `"术语"` + `"抽取器"` | `{"terms": [{"source":"堀北","target":"堀北","type":"人物","gender":"女"}]}` |
| `"回译译者"` | `{"backtranslations": ["逆0", ...]}`（按编号数） |
| `"保真度"` | `{"issues": []}` |
| `"章节梗概员"` | `"本章梗概：人物登场，情节推进。"` |
| `"全书概览员"` | `"全书概览：主线与人物关系，整体基调。"` |
| 其他 | `"{}"` 或空串 |

#### `tests/sample_data.py` — 测试样本数据

提供构造测试用 `Document` / `Chapter` / `Segment` 的辅助函数与固定样本。

#### `tests/__init__.py`

包标识，通常为空。

## `FakeClient` 机制

`llm/providers/fake.py:FakeClient` 是测试用的可编程 provider：

```python
class FakeClient(LLMClient):
    def __init__(self, handler: Optional[Callable[[Messages, str, bool], str]] = None)
    def complete(self, messages, *, tier="strong", json_mode=False,
                 max_tokens=None, stage=None) -> str
```

- `handler(messages, tier, json_mode) -> str`：用户注入的伪响应函数。
- `self.calls: list[dict[str, Any]]`：记录每次调用的入参（messages/tier/json_mode/max_tokens/stage），便于测试断言调用次数与参数。
- 默认行为：`json_mode` 返回 `"[]"`，否则返回空串。

测试时通过 `FakeClient(handler=routing_handler)` 注入路由 handler，即可离线跑完整条流水线。`Orchestrator` 接受 `client` 参数：

```python
orch = Orchestrator(config, client=FakeClient(handler=routing_handler))
```

## 测试设计要点

### 段对齐测试

`test_translator.py` 重点测试 `Translator.translate_batch` 的对齐保证：
- 正常情况：返回段数 = 输入段数。
- 模型返回段数不符：触发重试（`align_retry_limit` 次）。
- 重试耗尽：逐段兜底，从结构上保证 1:1。
- 非列表返回：抛 `AlignmentError`。

### 用量跟踪测试

`test_usage.py` 测试 `UsageTracker`：
- 双层归因（tier + stage）。
- `usage_delta` 非负差值。
- `merge_usage_summaries` 累加。
- cache_hit_rate 计算。

### Worker 协议测试

`test_app_worker.py` 测试 `EventWriter` 与 `run_worker`：
- `EventWriter.emit` 写一行 JSON（含 `protocolVersion`/`taskID`/`type`/`timestamp`）。
- `run_worker` 完成后 emit `completed`，含 `outputs` 与隔离的 `stateDirectory`。
- 用 `FakeOrchestrator` 替换真实 `Orchestrator`，避免触发真实翻译。

### 端到端 CLI 测试

`test_cli.py` 通过 Typer 的 `CliRunner` 调用命令，断言退出码与输出。使用 `FakeClient` 离线运行。

## 前端测试

### 运行

```bash
cd web
npm test          # vitest run
```

### 配置

`web/vitest.config.ts`（与 `vite.config.ts` 分离）配置 jsdom 环境与 testing-library。

`web/src/test-setup.ts` 注册 `@testing-library/jest-dom` 匹配器。

### 测试文件

- `web/src/App.test.tsx`：测试 `App` 组件渲染、书架交互、任务状态等。

### 依赖

- `@testing-library/react`：DOM 测试。
- `@testing-library/jest-dom`：jest DOM 断言匹配器。
- `jsdom`：浏览器环境模拟。

## 测试约定

- **不依赖真实 LLM API**：所有测试通过 `FakeClient` + 路由 handler 离线进行。
- **临时目录**：测试用 `tempfile.TemporaryDirectory()` 隔离 state_dir 与输出，避免污染工作区。
- **原子性**：每个测试独立构造 `Config` / `RunStore` / `Orchestrator`，不共享状态。
- **固定样本**：`tests/sample_data.py` 提供可复用的 Document/Chapter/Segment 构造辅助。
