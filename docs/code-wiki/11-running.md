# 11 · 项目运行与开发指南

## 环境要求

- **Python**：3.10+
- **包管理**：[uv](https://docs.astral.sh/uv/)（推荐）或 pip
- **Node.js**：仅前端开发或重新构建静态资源时需要
- **操作系统**：macOS / Linux / Windows

## 安装

### 后端（uv）

```bash
cd /Volumes/Data/Projects/wenyi
uv sync
```

`uv sync` 会根据 `pyproject.toml` 与 `uv.lock` 创建虚拟环境并安装全部依赖。

### 后端（pip）

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

### 前端（仅开发需要）

```bash
cd web
npm install
```

普通用户启动 Web UI 不需要安装 Node——发布 wheel 已包含 `web/dist` 静态资源（`pyproject.toml` 中 `[tool.hatch.build.targets.wheel.force-include]` 把 `web/dist` 映射到 `trans_novel/web_dist`）。

## 运行

### CLI 翻译

```bash
# 设置模型 API Key（DeepSeek 示例）
export DEEPSEEK_API_KEY=sk-...

# 翻译（连续全流程，可断点续跑）
uv run trans-novel translate book.epub

# 中断后继续
uv run trans-novel resume book.epub

# 查看进度
uv run trans-novel status book.epub

# 只翻指定章（调试用，不做收尾）
uv run trans-novel translate book.epub --chapter 3

# 同时生成单语版和双语版
uv run trans-novel translate book.epub --bilingual

# 仅生成双语版
uv run trans-novel translate book.epub --no-mono --bilingual

# 覆盖配置：关闭润色、关闭 QA
uv run trans-novel translate book.epub --no-polish --no-qa

# 指定输出格式与路径
uv run trans-novel translate book.epub --format txt --out /path/to/output.txt
```

首次运行 CLI 时会自动在当前目录生成默认 `config.yaml`（由 `Config.create_default_file` 原子创建）。修改后无需改代码。

### Web UI

```bash
# 方式一：直接启动（已安装 wheel）
trans-novel-web

# 方式二：从源码运行
uv run trans-novel-web

# 方式三：启动脚本（自动 sync 依赖并打开浏览器）
./script/start-webui.sh        # macOS / Linux
script\start-webui.bat          # Windows
```

默认地址 `http://127.0.0.1:8787`；端口被占用时顺延选择下一个可用端口（`available_port` 在 preferred~preferred+100 范围内探测）。启动脚本会自动打开默认浏览器。

端口可用环境变量覆盖：

```bash
WENYI_WEB_PORT=9000 uv run trans-novel-web
```

启动后 stdout 会打印 `WENYI_WEB_URL=...` 供脚本读取。

### 数据存储位置

| 入口 | 默认位置 |
|------|----------|
| CLI | `<源文件目录>/output/`（产物）+ `<cwd>/state/<book-slug>/`（运行状态） |
| Web UI | `~/.wenyi-webui/`（books/covers/outputs/state/tasks/settings.json） |

Web UI 的图书、任务状态和内部产物默认保存在 `~/.wenyi-webui`，完成后的文件可从工作台下载。所有数据均保存在本机文件和任务专属状态中，不需要数据库、Redis 或容器服务。

## 配置

主配置文件 `config.yaml`（首次运行自动生成）。详见 [02-config.md](02-config.md) 与用户文档 [`docs/configuration.md`](../configuration.md)。

关键配置项：

```yaml
language:
  source: auto        # auto 由模型识别；也可写死 ja/en/ko/ru/de/fr/es/it/pt
  target: zh

llm:
  provider: deepseek  # deepseek|openai|openrouter|openai-compatible|ollama|vllm|fake
  base_url: https://api.deepseek.com
  api_key_env: DEEPSEEK_API_KEY   # 环境变量名（不直接存密钥）
  tiers:
    strong: { model: deepseek-v4-pro, options: { thinking: true, reasoning_effort: high } }
    cheap:  { model: deepseek-v4-flash, options: { thinking: true, reasoning_effort: high } }
    fast:   { model: deepseek-v4-flash, options: { thinking: false } }
```

API Key 通过环境变量传入，**不写入配置文件**：

```bash
export DEEPSEEK_API_KEY=sk-...
# 或 OpenAI
export OPENAI_API_KEY=sk-...
# 或 OpenRouter
export OPENROUTER_API_KEY=sk-...
```

`openai-compatible` / `ollama` / `vllm` 可不设 api_key（`KEY_OPTIONAL_PROVIDERS`）。

## 前端开发

```bash
cd web
npm install
npm run dev      # 启动 Vite 开发服务器（默认 5173）
```

开发时 Vite 把 `/api` 请求代理到 `http://127.0.0.1:8787`（后端必须同时运行）。修改前端后访问 `http://localhost:5173`。

构建静态资源（更新 `web/dist`）：

```bash
cd web
npm run build    # 先 tsc -b 类型检查，再 vite build
```

源码仓库保留 `web/dist` 供本地运行；修改前端后运行 `npm run build` 更新该目录。

## 构建 wheel

```bash
uv build          # 生成 dist/*.whl 与 sdist
```

`pyproject.toml` 配置：
- 构建后端：hatchling
- wheel 包：`trans_novel`
- force-include：`web/dist` → `trans_novel/web_dist`（前端静态资源打入 wheel）
- sdist 排除：`/.build`、`/.codegraph`、`/tasks`、`/web/node_modules`、`/web/*.tsbuildinfo`

## 测试

```bash
uv run pytest                    # 全部测试
uv run pytest tests/test_translator.py   # 单个测试文件
uv run pytest -k translator       # 按名称筛选
```

前端测试：

```bash
cd web
npm test          # vitest run
```

测试体系详见 [12-testing.md](12-testing.md)。

## 调试技巧

### 查看 run 状态目录

```bash
ls state/<book-slug>/
# manifest.json  chapters/  context.json  analysis.json
# usage.json  glossary.db  report.json  events.jsonl
```

- `events.jsonl` 是对账日志，包含每批 `batch_translated` 的源/译对照、`autofix_applied` 改写前后、`usage_summary` 增量等。
- `manifest.json` 的 `chapters[*].status` 显示各章进度。
- `usage.json` 显示累计 token 用量与缓存命中率。

### 使用 fake provider 调试流水线

`config.yaml` 设 `llm.provider: fake`，或环境变量 + 临时配置：

```yaml
llm:
  provider: fake
```

`FakeClient` 默认行为：`json_mode` 返回 `"[]"`，否则返回空串。测试时可通过 `FakeClient(handler=...)` 注入自定义响应。详见 [12-testing.md](12-testing.md)。

### 细粒度工具命令

```bash
# 术语库管理
uv run trans-novel tools glossary book.epub list
uv run trans-novel tools glossary book.epub conflicts
uv run trans-novel tools glossary book.epub resolve "原词" "译名"

# 重新回填生成译文文件
uv run trans-novel tools assemble book.epub --format epub --bilingual

# 全书跨章一致性扫描
uv run trans-novel tools qa book.epub

# 生成 QA 报告
uv run trans-novel tools report book.epub
```

详见 [09-cli.md](09-cli.md)。

### Windows 控制台中文

`cli.py:_configure_windows_console` 在 Windows 上把 `sys.stdout` / `sys.stderr` reconfigure 为 `utf-8` 编码（errors="replace"），PyInstaller 单文件启动时尤其需要。

## CI

`.github/workflows/build.yml` 定义 GitHub Actions 构建流程（具体内容请查看文件）。

## 常见问题

### 端口被占用

Web UI 会自动顺延到下一个可用端口（preferred~preferred+100）。也可用 `WENYI_WEB_PORT` 显式指定。

### 自动识别源语言失败

`source: auto` 由模型检测；失败时报错"自动识别源语言失败"。解决：在 `config.yaml` 的 `language.source` 指定 ISO 639-1 语言代码（如 `ja`/`en`/`ko`/`ru`/`fr`/`de`/`es`）。

### database is locked

`glossary.db` 启用 SQLite WAL 模式 + `busy_timeout=5000` 兼顾并发。若仍遇到锁冲突，通常是 Web UI 编辑与翻译 worker 长时间同时写——暂停任务后再做大规模术语编辑。

### 翻译中断后续跑

直接再次运行 `uv run trans-novel translate book.epub` 或 `uv run trans-novel resume book.epub`。系统会自动检测 `state/<book-slug>/manifest.json`，从断点处续跑（章级 / 批级术语检查点 / 批级译文复用三层粒度）。
