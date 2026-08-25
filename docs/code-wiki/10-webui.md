# 10 · Web UI 后端与前端

文译提供一个轻量的本地单用户 Web 工作台，复用同一套 Python 翻译引擎。它只监听本机回环地址（`127.0.0.1:8787`），不提供远程账户或多用户服务。

## 后端：`trans_novel/web.py`

FastAPI 应用，提供图书管理、任务编排、术语库/审校/导出等完整 API，并把 `/api` 之外的根路径挂载为静态前端。

### 核心配置常量

```python
SUPPORTED_BOOK_TYPES = {".epub", ".fb2", ".txt"}
MAX_UPLOAD_BYTES = 256 * 1024 * 1024       # 256 MB 上限
KEY_OPTIONAL_PROVIDERS = {"openai-compatible", "ollama", "vllm"}
```

### Pydantic 模型（请求/响应）

- `TierSettings(model: str, thinking: bool = False)`：单档模型配置。
- `WebSettings`：全局设置（provider/base_url/api_key/reasoning_style/glow_mode/source_lang/output_format/timeout/max_retries/三档模型/输出开关/流水线开关）；含校验器（source_lang 必须 auto 或 ISO 639-1、base_url 必须 http/https、mono 与 bilingual 不可同时关闭）。
- `StartTaskRequest(book_id, output_format=None)`
- `ConnectionModels(strong, cheap, fast)` + `TestConnectionRequest(provider, base_url, api_key, models)`
- `GlossaryTermRequest(source, target, reading, type, gender, aliases, first_chapter, note)`
- `ConflictResolutionRequest(choice: "current" | "proposed")`
- `AnalysisUpdateRequest(style_guide, book_synopsis)`
- `SegmentUpdateRequest(target)`
- `ExportRequest(format, mono, bilingual, bilingual_order, about_page)`

### `WebStore` — 持久化存储管理

根目录默认 `~/.wenyi-webui`。

```python
class WebStore:
    def __init__(self, root: Path)
        # 创建 books/covers/outputs/state/tasks 子目录，根目录权限 0o700
    def settings() -> WebSettings / save_settings(settings)
    def books() -> list[dict] / save_books(books)
    def groups() / save_groups(groups)
    def task_file(task_id) -> Path
    def tasks() -> list[dict]   # 按 created_at 倒序
    def pause_running_tasks()   # 服务重启时把运行中任务标为 paused
```

### `TaskManager` — 任务生命周期与子进程管理

```python
class TaskManager:
    def task_lock(task_id) -> threading.RLock   # 每个任务一把可重入锁
    def get(task_id) / save(task) / update(task_id, change)
    def workspace(task) -> RunStore | None       # 从 run_dir 或 state_dir 探测 manifest.json
    def public(task) -> dict                     # 剥离内部字段，outputs 转文件名列表
    def publish(task_id, event)                  # 推送到所有 SSE 监听队列
    def _write_config(path, settings, state_dir) # dump 成 worker 用的 YAML 配置
    def start(book, output_format="epub", task_id=None) -> dict
    def stop(task_id)                            # SIGTERM（8 秒等待），仍不退则 kill
    def shutdown()                               # 优雅关闭所有运行中的任务
    async def events(task_id) -> AsyncIterator[str]  # SSE 流
```

#### `start` 关键逻辑

- 校验图书存在、避免重复运行。
- 复用 previous 任务的 config/state；若已有 snapshot 则要求 provider/base_url 一致才能继续。

#### `_run` 子进程协议

用 `asyncio.create_subprocess_exec` 拉起 `python -m trans_novel.app_worker` 子进程，把 `WENYI_WEB_API_KEY` 注入环境：
- 逐行读 stdout JSON 事件，按 `phase/progress/completed/failed` 更新任务并 publish。
- stderr 尾部保留 8KB 用于失败诊断。

#### `events` SSE 流

先发 `snapshot` 事件（含完整任务对象），之后从 `asyncio.Queue` 取事件推送，**20 秒无事件发 `: keepalive` 心跳**。

### `create_app` — FastAPI 应用构造

```python
def create_app(data_dir=None, web_dir=None) -> FastAPI
```

- **中间件 `reject_cross_site_writes`**：POST/PUT/PATCH/DELETE 时校验 `Origin` 与 `sec-fetch-site`，仅允许本机页面写数据（防 CSRF）。
- **lifespan**：退出时 `await manager.shutdown()`。
- **静态文件挂载**：优先 `trans_novel/web_dist`（打包发布），其次 `web/dist`（开发构建）。

### `available_port` / `main`

```python
def available_port(host, preferred)  # 在 preferred~preferred+100 范围内探测可用端口
def main()                           # 默认 127.0.0.1:8787（WENYI_WEB_PORT 可覆盖）
```

## 后端：`trans_novel/app_worker.py`

本机客户端使用的 JSON Lines worker。stdout 只承载协议事件，stderr 用于诊断 traceback。被 `web.py:TaskManager._run` 通过 `python -m trans_novel.app_worker` 拉起。

### 协议常量

```python
PROTOCOL_VERSION = 1
```

### `WorkerRequest`

```python
@dataclass(frozen=True)
class WorkerRequest:
    task_id: str
    input_path: str
    output_path: str
    state_dir: str
    config_path: str
    out_format: str = "epub"
```

### `EventWriter`

```python
class EventWriter:
    def __init__(self, task_id, *, stream=sys.stdout)
    def emit(self, event_type, **payload)
        # 写一行 JSON（含 protocolVersion/taskID/type/timestamp + payload），立即 flush
```

### `run_worker`

```python
def run_worker(request: WorkerRequest, *, stream=sys.stdout) -> int
```

流程：
1. emit `ready`（workerVersion/pythonVersion/executable）。
2. 加载 `Config`，设置 state_dir，创建输出目录。
3. 定义 `on_phase(name, label)` 与 `on_progress(done, total, label)` 回调，转换为 `phase`/`progress` 事件（含 fraction）。
4. 调用 `Orchestrator(config).run_all(input_path, progress=..., phase=..., out_format=..., out_path=...)`。
5. 完成后 emit `completed`，包含 `outputs/summary/stateDirectory`。
6. 捕获 `KeyboardInterrupt`（SIGTERM 转换为该异常）→ emit `failed code=cancelled`，返回 130；其他异常 → emit `failed code=worker_error`，返回 1。

`main` 注册 SIGTERM → KeyboardInterrupt，调用 `run_worker`。

## 后端：`trans_novel/book_inspector.py`

无第三方依赖的图书元数据检查器，供 Web UI 导入图书时提取元数据。

### 关键函数

```python
def inspect_book(path: str, cover_directory: str, book_id: str) -> dict
```

- `.txt`/其他：返回空元数据（title 取文件名 stem）。
- `.fb2`：用 `xml.etree.ElementTree` 解析，从 `title-info` 提取作者/书名/语言/简介/类型；从 `publish-info` 提取出版社/年份/ISBN；从 `coverpage/image` 找 `binary` base64 解码写盘作为封面；`chapterCount` 按 `section` 标签计数。
- `.epub`：解 zip 读 OPF，扫描 `<item>` 构建 manifest，统计 `<itemref>` 数为章节计数，从 `<meta name="cover">` 取 cover id；从 manifest 中按 `cover-image` 属性或 id 匹配定位封面 item，从 zip 解出写盘。
- 返回字段：`title, authors, language, publisher, publicationDate, identifier, description, subjects, chapterCount, fileSize, coverPath`。

## API 端点列表

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/settings` | 获取设置（api_key 置空，返回 has_api_key） |
| PUT | `/api/settings` | 保存设置（provider 不变且 api_key 空时保留旧 key） |
| POST | `/api/settings/test-connection` | 测试模型服务连接 |
| GET | `/api/books` | 图书列表 |
| POST | `/api/books` | 上传图书（multipart，≤256MB） |
| GET | `/api/books/{book_id}/cover` | 图书封面图 |
| DELETE | `/api/books/{book_id}` | 删除图书（运行中禁删） |
| PATCH | `/api/books/{book_id}/group` | 移动图书到分组 |
| GET | `/api/groups` | 分组列表 |
| POST | `/api/groups` | 创建分组 |
| PATCH | `/api/groups/{group_id}` | 重命名分组 |
| DELETE | `/api/groups/{group_id}` | 删除分组（组内图书 group_id 置空） |
| GET | `/api/tasks` | 任务列表 |
| GET | `/api/tasks/{task_id}` | 任务详情 |
| POST | `/api/tasks` | 启动新任务 |
| POST | `/api/tasks/{task_id}/stop` | 暂停任务 |
| POST | `/api/tasks/{task_id}/resume` | 继续任务 |
| GET | `/api/tasks/{task_id}/stream` | SSE 任务事件流 |
| GET | `/api/tasks/{task_id}/chapters` | 章节列表 |
| GET | `/api/tasks/{task_id}/chapters/{chapter_index}` | 章节详情 |
| PATCH | `/api/tasks/{task_id}/chapters/{chapter_index}/segments/{segment_index}` | 编辑单段译文 |
| POST | `/api/tasks/{task_id}/chapters/{chapter_index}/review-complete` | 标记章节审校完成 |
| GET | `/api/tasks/{task_id}/analysis` | 风格概要 |
| PATCH | `/api/tasks/{task_id}/analysis` | 编辑风格指南/全书概要 |
| GET | `/api/tasks/{task_id}/glossary/terms` | 术语列表 |
| POST | `/api/tasks/{task_id}/glossary/terms` | 新增/更新术语 |
| DELETE | `/api/tasks/{task_id}/glossary/terms/{source}` | 删除术语 |
| GET | `/api/tasks/{task_id}/glossary/conflicts` | 术语冲突列表 |
| POST | `/api/tasks/{task_id}/glossary/conflicts/{conflict_id}/resolve` | 解决冲突 |
| GET | `/api/tasks/{task_id}/usage` | Token 用量统计 |
| GET | `/api/tasks/{task_id}/events` | 事件日志 |
| GET | `/api/tasks/{task_id}/exports` | 导出记录列表 |
| POST | `/api/tasks/{task_id}/exports` | 重新导出 |
| GET | `/api/tasks/{task_id}/exports/{export_id}/download` | 下载指定导出 |
| GET | `/api/tasks/{task_id}/outputs/{name}` | 下载原始产物 |
| (mount) | `/` | 静态前端 |

## 前端：`web/`

React 19 + Vite + TypeScript 单页应用。**不使用 URL 路由**（无 react-router），导航通过组件内 state 切换。

### `web/package.json`

- **运行时依赖**：`@phosphor-icons/react`（图标）、`motion`（Framer Motion 新包名，动画）、`react` / `react-dom` 19。
- **开发依赖**：`@vitejs/plugin-react`、`testing-library`、`jsdom`、`typescript ~5.9`、`vite ^7`、`vitest ^3`。
- **脚本**：`dev`（vite）、`build`（`tsc -b && vite build`）、`preview`、`test`（vitest run）。

### `web/vite.config.ts`

```ts
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8787" } },
  build: { outDir: "dist" },
});
```

开发模式把 `/api` 代理到后端，前端用相对路径 `fetch("/api/...")`。

### `web/src/App.tsx` — 根组件

state：`books/groups/tasks/settings/selectedBook/settingsOpen/glowSaving/taskActions/busy/error`。

主要组件：
- **`App()`**：根组件。`refresh()` 并行拉取 books/groups/tasks/settings；`useEffect` 监听 `runningTaskIds`，为每个运行中任务开 `EventSource(/api/tasks/{id}/stream)`；`run()` 启动翻译任务；渲染 `TopBar` + `LibraryRail` + `focus-panel` + `SettingsSheet`。
- **`BookCover`**：封面图，失败回退 `Books` 图标占位。
- **`BookOverview`**：元数据网格 + 内容简介。
- **`TopBar`**：品牌 + 运行计数 + 设置按钮。
- **`LibraryRail`**：左侧书架栏，支持分组创建/重命名/删除、图书拖拽移动、上传、删除（HTML5 drag-and-drop）。
- **`CompactTaskStatus`**：紧凑任务状态条，含进度条、暂停/继续/重新翻译按钮、下载译文链接。
- **`EmptyWorkspace`**：空状态拖拽上传区。
- **`SettingsSheet`**：右侧滑出抽屉，两页：模型配置 + WebUI 设置。

### `web/src/AdvancedWorkspace.tsx` — 任务工作区

当前图书有任务时显示，通过 7 个 tab 组织任务深层数据：

| Tab | 内容 |
|-----|------|
| overview | 概览（BookOverview + CompactTaskStatus） |
| glossary | 术语库（搜索/筛选/添加/冲突解决/删除） |
| analysis | 风格概要（体裁/语调/叙事/角色，可编辑风格指南与全书概要） |
| review | 逐章审校（章节导航 + 段落卡片 + 保存译文 + 标记完成） |
| exports | 重新导出（格式/内容选项 + 历史产物下载） |
| events | 运行事件（按类型筛选，5 秒轮询） |
| usage | Token 用量（5 个 Metric 卡片 + 按档位/阶段明细） |

辅助组件：`PanelState({loading, ready, empty, children})` 统一空状态/加载态包装。

### `web/src/api.ts` — API 封装

```typescript
async function request<T>(path: string, init?: RequestInit): Promise<T>
```
fetch 封装，非 2xx 时解析 `body.detail`（字符串或数组拼接为分号分隔），统一抛 Error。

`api` 对象方法与后端端点一一对应：`books/groups/tasks/settings/upload/start/stop/resume/chapters/chapter/saveSegment/completeReview/analysis/glossaryTerms/...`。

注意：SSE 流（`/api/tasks/{id}/stream`）不通过 `api` 对象，由 `App.tsx` 直接 `new EventSource(...)`；下载链接也是直接用 URL，不走 fetch 封装。

## 前后端通信

**通信协议**：HTTP + JSON（REST 风格），辅以 SSE 实时推送。

**部署形态**：
- **生产/打包模式**：`python -m trans_novel.web` 启动 uvicorn（默认 127.0.0.1:8787），FastAPI 通过 `StaticFiles` 直接托管前端静态文件。前端与后端同源，无 CORS。
- **开发模式**：`vite dev` 启动 Vite 开发服务器（默认 5173），`vite.config.ts` 中 `server.proxy["/api"]` 把所有 `/api` 请求代理到后端。

**通信通道分四类**：

1. **普通 REST 请求**：`api.ts` 的 `request<T>(path, init)` 封装 fetch。
2. **SSE 实时推送**：`App.tsx` 对每个运行中任务 `new EventSource`。后端 `TaskManager.events` 是 async generator，先发 `snapshot` 再循环读队列，20 秒无事件发 keepalive。前端收到 snapshot 直接替换 task，其他事件触发 `api.tasks()` 全量重拉。事件源头是 `app_worker.py` 子进程 stdout 的 JSON Lines。
3. **文件下载**：直接用 `<a href>` 或 `<img src>`，由 `FileResponse` 流式返回。
4. **文件上传**：`api.upload(file)` 用 `FormData` + `POST /api/books`，后端 `UploadFile` 流式接收（1MB chunk），超 256MB 报 413。

## 安全机制

- 后端中间件 `reject_cross_site_writes`：POST/PUT/PATCH/DELETE 校验 `Origin` 与 `sec-fetch-site`，仅允许本机页面写数据。
- `WebStore` 根目录权限 0o700，`_atomic_json` 写文件权限 0o600。
- API Key 通过环境变量 `WENYI_WEB_API_KEY` 传给 worker 子进程，不写入 YAML 配置。
- `GET /api/settings` 返回时 `api_key` 置空，仅返回 `has_api_key` 布尔。

## 任务执行链路

1. 前端 `api.start(bookId)` → `POST /api/tasks` → `TaskManager.start` → 创建任务 JSON、写 YAML 配置、`asyncio.create_task(_run_job)`。
2. `_run_job` → `_run` → `asyncio.create_subprocess_exec("python", "-m", "trans_novel.app_worker", ...)` 拉起 worker 子进程。
3. worker `run_worker` emit `ready` → 加载 Config → `Orchestrator.run_all` 执行全流程，通过 `on_phase`/`on_progress` 回调 emit 事件 → 完成 emit `completed`。
4. `TaskManager._run` 逐行读 stdout JSON，按事件类型更新 task 状态字段并 `save`，同时 `publish` 到 SSE 队列。
5. 前端 `EventSource` 收到事件 → 更新 `tasks` state → 触发 `AdvancedWorkspace` 各 Panel 重新轮询（5 秒间隔）。
6. 用户暂停 → `api.stop` → `TaskManager.stop` 发 SIGTERM → worker 捕获 KeyboardInterrupt emit `failed code=cancelled` → task 标 paused。
7. 用户继续 → `api.resume` → `TaskManager.start(task_id=...)` 复用原 config/state_dir 继续运行。
8. 用户编辑译文 → `api.saveSegment` → 写入 `RunStore` 章节文件，task 标 `outputs_stale=true`、`content_revision++`。
9. 用户重新导出 → `api.createExport` → 在 `asyncio.to_thread` 中调用 `assemble(writer.py)` 同步生成新文件。
