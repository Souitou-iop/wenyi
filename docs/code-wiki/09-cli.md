# 09 · 命令行接口（cli）

`trans_novel/cli.py` 基于 Typer + Rich，是 CLI 用户的主要入口。

## 文件：`trans_novel/cli.py`

### 设计原则

> 日常只需 `translate` 一个命令：连续全流程（分析→翻译→审校→一致性 QA→报告→回填 EPUB），中断后再次运行自动续跑。其余 `resume` / `status` 为常用辅助；细粒度/调试工具收敛到 `tools`：glossary / assemble / qa / report。

### 入口与全局配置

```python
app = typer.Typer(cls=_ConfigInitializingGroup, add_completion=False,
                  help="多 Agent 小说翻译系统（多语言 → 中文）")
tools_app = typer.Typer(add_completion=False,
                        help="高级/调试工具：glossary（术语表）/ assemble（回填）/ qa / report")
app.add_typer(tools_app, name="tools")

def main() -> None:
    app()
```

#### `_ConfigInitializingGroup`

所有 CLI 调用在 Click 分派或早退前都检查默认配置。`main` 重写：从 `sys.argv` 提取 `--config`/`-c`（`_config_path_from_args`），调用 `Config.create_default_file(config_path)`，确保 `--help` 等早退命令也会初始化配置。

#### `_configure_windows_console`

让 Windows 控制台能输出中文；PyInstaller 单文件启动时尤其需要。模块导入时立即调用一次，把 `sys.stdout` / `sys.stderr` reconfigure 为 `utf-8`（errors="replace"）。

### 配置加载

```python
_CONFIG = {"path": "config.yaml"}

@app.callback()
def _root(config: str = typer.Option("config.yaml", "--config", "-c", help="配置文件路径")):
    _CONFIG["path"] = config

def _load_config() -> Config:
    return Config.load(_CONFIG["path"])
```

全局 `--config`/`-c` 选项指定配置文件路径，默认 `config.yaml`。

### 辅助函数

```python
def _require_input_file(input_path: str) -> None
    # 文件不存在则报错退出
def _runstore_for(config: Config, input_path: str) -> RunStore
    # 加载文档 → 推断 run_dir = state_dir/<slug(title)> → 返回 RunStore(create=False)
```

### 主命令：`translate` / `resume`

```python
@app.command()
def translate(
    input: str = typer.Argument(..., help="输入文件（.epub / .txt / .md）"),
    chapter: Optional[int] = typer.Option(None, "--chapter", help="只翻指定章（调试用，不做收尾）"),
    fmt: str = typer.Option("epub", "--format", help="输出格式：epub | txt"),
    out: Optional[str] = typer.Option(None, "--out", help="输出路径"),
    polish: Optional[bool] = typer.Option(None, "--polish/--no-polish", help="覆盖配置文件中的润色开关"),
    qa: Optional[bool] = typer.Option(None, "--qa/--no-qa", help="覆盖配置文件中的一致性 QA 开关"),
    mono: Optional[bool] = typer.Option(None, "--mono/--no-mono", help="覆盖单语版产出开关"),
    bilingual: Optional[bool] = typer.Option(None, "--bilingual/--no-bilingual", help="覆盖双语版产出开关"),
)
```

```python
@app.command()
def resume(input: str, fmt: str = typer.Option("epub", "--format"))
    # 断点续跑（等价于再次 translate）
```

`translate` 与 `resume` 共享 `_translate_impl`，避免 CLI 参数转发漂移。

#### `_translate_impl` 流程

1. 校验输入文件存在。
2. 加载配置，按命令行参数覆盖 `polish` / `mono` / `bilingual`。
3. 实例化 `Orchestrator(config)`。
4. 用 Rich `Progress` 显示进度（`SpinnerColumn` + `BarColumn` + `MofNCompleteColumn` + `TimeElapsedColumn`）。
5. `chapter is not None` → 只翻指定章（`orch.run(only_chapter=chapter, progress=cb)`），打印状态目录与用量，返回。
6. 否则 `orch.run_all(input_path, progress=cb, out_format=fmt, out_path=out, do_qa=qa)` 跑完整流水线。
7. 打印完成摘要（章数/术语数/一致性问题数）与用量，打印译文路径。

#### 进度回调

```python
def cb(done: int, total: int, label: str) -> None
```
- `total > 0`：更新 `completed/total/description`。
- `total == 0`：Rich 的 `update(total=None)` 表示"不修改 total"，无法从上一阶段的确定总数切回滚动模式；**重建任务**以清除残留的章节/段落计数。

#### `_print_usage`

打印本书累计 token 用量与分档缓存命中率（无数据时静默跳过）：
- 总量：total_tokens（提示 / 生成），缓存命中率（命中 / 未命中 tok）。
- 按档位：每档 total_tokens、调用次数、缓存命中率。
- 按阶段：每阶段 total_tokens（提示 / 生成）、调用次数、缓存命中率，按总 token 降序。

### 查询命令：`status`

```python
@app.command()
def status(input: str)
    # 查看各章进度与术语库统计
```

打印书名、格式、语言对，用 Rich `Table` 显示各章状态（`✓` 完成 / `·` 未完成）与术语库统计 `{terms, open_conflicts, tm_entries}`。

### 工具命令：`tools`

#### `tools glossary`

```python
@tools_app.command()
def glossary(input: str, action: str = "list", arg1: Optional[str] = None, arg2: Optional[str] = None)
    # action: list | conflicts | resolve
```

- `list`：用 Rich `Table` 显示所有术语（原文/译文/类型/状态）。
- `conflicts`：列出未解决冲突（现有译法 vs 提议译法，附章节）。
- `resolve`：调 `resolver.resolve(g, arg1, arg2)` 人工裁定最终译法。

#### `tools assemble`

```python
@tools_app.command()
def assemble(input: str, out: Optional[str] = None, fmt: str = "epub",
             mono: Optional[bool] = None, bilingual: Optional[bool] = None)
    # 回填生成译文文件（默认 EPUB）
```

按 `mono`/`bilingual` 开关调 `do_assemble`（即 `assemble/writer.assemble`）生成单语/双语产物。都关时兜底产单语。

#### `tools qa`

```python
@tools_app.command()
def qa(input: str)
    # 全书跨章一致性扫描
```

实例化 `ConsistencyChecker(build_client(config), config)`，调 `.check(store, g)`，打印一致性问题列表（`[type] detail (where)`）。

#### `tools report`

```python
@tools_app.command()
def report(input: str)
    # 生成 QA 报告（漏译与术语冲突汇总）
```

调 `build_report(store, g)`，写 `report.json`，打印摘要（章节/术语/待裁决冲突/审校问题/回译疑点）。

## `__main__.py`

```python
"""`python -m trans_novel` 与 PyInstaller 的统一入口。"""
from trans_novel.cli import main

if __name__ == "__main__":
    main()
```

仅从 `trans_novel.cli` 导入 `main` 并调用，真正的 CLI 逻辑在 `cli.py`。

## 命令一览

```bash
# 主命令
trans-novel translate <input> [options]    # 翻译（连续全流程，可断点续跑）
trans-novel resume <input> [--format epub] # 断点续跑（等价 translate）
trans-novel status <input>                 # 查看进度

# 工具命令
trans-novel tools glossary <input> list
trans-novel tools glossary <input> conflicts
trans-novel tools glossary <input> resolve <source> <target>
trans-novel tools assemble <input> [--out PATH] [--format epub] [--bilingual]
trans-novel tools qa <input>
trans-novel tools report <input>

# 全局选项
trans-novel --config <path> <command>      # 指定配置文件
trans-novel --help                         # 帮助
```

## 入口点配置

`pyproject.toml` 注册两个入口点：

```toml
[project.scripts]
trans-novel = "trans_novel.cli:main"
trans-novel-web = "trans_novel.web:main"
```

安装 wheel 后可直接使用 `trans-novel` 与 `trans-novel-web` 命令。从源码运行用 `uv run trans-novel ...` 或 `python -m trans_novel ...`。
