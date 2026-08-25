# 01 · 项目整体架构

## 设计哲学

文译不是"逐句翻译器"，而是**针对长篇小说的翻译质量**构建的多 Agent 协同系统。核心设计取舍：

1. **全书理解优先**：翻译前先预扫源文生成逐章梗概 + 全书概览，作为恒定前缀注入每章翻译 prompt，让译者"对全书有理解"（伏笔、人物弧光、谜底不会在早期章节盲译）。
2. **滚动上下文 + 实时术语库**：章内逐批串行翻译，每批把刚译出的译文并入滚动上下文供下一批参照；术语实时抽取入库，立即可供同章后续批次使用。
3. **多道质量保障**：翻译 → 润色 → 标点规范化 → 章末分块并行审校 → 严重项定向重译 → 回译抽检 → 全书跨章一致性 QA。
4. **段对齐硬约束**：翻译器输入 N 段必须输出 N 段译文，三级策略（整批翻译 → 重试 → 逐段兜底）从结构上杜绝漏译；润色器返回段数不符直接保留原译文。
5. **断点续跑**：三层粒度（章级状态 / 批级术语检查点 / 批级译文复用），中断后再次运行自动续跑。
6. **缓存友好**：system prompt 全静态、user prompt 按"静态→动态"排列，最大化 DeepSeek 前缀缓存命中。
7. **本地单用户**：Web UI 只监听 127.0.0.1，所有数据落本机文件，不依赖数据库/Redis/容器。

## 顶层目录结构

```
wenyi/
├── trans_novel/          # Python 后端包（翻译引擎 + CLI + Web API）
│   ├── __init__.py
│   ├── __main__.py       # python -m trans_novel 入口
│   ├── cli.py            # Typer CLI（translate / resume / status / tools）
│   ├── config.py         # 配置加载（pydantic v2）
│   ├── web.py            # FastAPI Web UI 后端
│   ├── app_worker.py     # Web 任务子进程 worker（JSON Lines 协议）
│   ├── book_inspector.py # 图书元数据提取（无第三方依赖）
│   ├── agents/           # 翻译 Agent（分析/翻译/审校/润色/一致性）
│   ├── assemble/         # 回填组装（EPUB/TXT 生成 + 报告 + 真实 Translator）
│   ├── glossary/         # 术语库 + 翻译记忆库（SQLite）
│   ├── ingest/           # 输入解析（EPUB/FB2/TXT）与切分
│   ├── llm/              # LLM Provider 抽象层（多服务商）
│   ├── pipeline/         # 流水线编排 + 状态持久化 + 滚动上下文
│   └── postprocess/      # 后处理（标点规范化）
├── web/                  # 前端项目（React 19 + Vite + TypeScript）
│   ├── src/
│   │   ├── App.tsx                 # 根组件（书架 + 焦点面板 + 设置抽屉）
│   │   ├── AdvancedWorkspace.tsx   # 任务工作区（7 个 tab）
│   │   ├── api.ts                  # 后端 API 封装
│   │   ├── main.tsx                # React 入口
│   │   └── styles.css
│   ├── dist/             # 构建产物（被 wheel 打包）
│   ├── package.json
│   └── vite.config.ts    # 开发代理 /api → 127.0.0.1:8787
├── tests/                # 单元测试（pytest + Fake LLM）
├── docs/                 # 用户文档 + Code Wiki
├── script/               # 启动脚本（macOS/Linux/Windows）
├── config.yaml           # 默认配置（首次运行自动生成）
├── pyproject.toml        # Python 项目配置（hatchling 构建）
└── README.md
```

## 模块依赖关系

下图展示后端模块的依赖方向（箭头 = "依赖于"）：

```
                          ┌──────────────┐
                          │   cli.py     │  ← 用户入口
                          │   web.py     │  ← 用户入口
                          └──────┬───────┘
                                 │
                                 ▼
                       ┌─────────────────┐
                       │  pipeline/      │
                       │  orchestrator   │  ← 流水线编排核心
                       └──────┬──────────┘
                              │
        ┌─────────────────────┼──────────────────────┐
        │                     │                      │
        ▼                     ▼                      ▼
  ┌──────────┐         ┌──────────┐           ┌──────────┐
  │ agents/  │◄────────│glossary/ │           │ ingest/  │
  │ (Agent)  │         │ (Store)  │           │ (Doc)    │
  └────┬─────┘         └────┬─────┘           └────┬─────┘
       │                    │                      │
       ▼                    │                      │
  ┌──────────┐              │                      │
  │  llm/    │◄─────────────┘                      │
  │ (Client) │                                     │
  └────┬─────┘                                     │
       │                                           │
       ▼                                           ▼
  ┌──────────┐                              ┌──────────────┐
  │ config.py│◄─────────────────────────────│ assemble/    │
  │ (Config) │                              │ (writer)     │
  └──────────┘                              └──────┬───────┘
                                                   │
                                                   ▼
                                            ┌──────────────┐
                                            │ postprocess/ │
                                            │ (punct)      │
                                            └──────────────┘
```

**关键依赖说明**：

- `pipeline/orchestrator` 是唯一的全局编排者，**直接依赖几乎所有其他模块**。
- `agents/` 与 `glossary/extractor.py` 都继承 `agents/base.py:Agent`，通过 `LLMClient` 调用模型。
- `llm/` 是纯传输层，不掺业务回退（业务回退在 `Agent._ask_json`）。
- `ingest/` 与 `glossary/` 之间**没有直接 import**，通过 orchestrator 间接协作。
- `assemble/` 依赖 `ingest/models.py` 的数据结构（`Segment.anchor` / `Chapter.template`）做回填定位。
- `config.py` 被几乎所有模块依赖，是配置的唯一来源。
- `postprocess/punct.py` 只被 `pipeline/orchestrator.py` 与 `assemble/writer.py` 调用。

## 翻译数据流

一次完整的 `trans-novel translate book.epub` 调用，数据流如下：

```
book.epub
   │
   ▼  ingest/segmenter.load_document()
Document { title, chapters: [Chapter { segments: [Segment] }] }
   │
   ▼  pipeline/runstore.RunStore.init_from_document()
state/<book-slug>/manifest.json + chapters/ch{n}.json
   │
   ▼  Orchestrator.prepare()
   │   ├─ _detect_language_ai()  → source_lang (auto 时)
   │   ├─ Analyzer.analyze(sample)  → analysis.json
   │   └─ Analyzer.seed_glossary()  → glossary.db (种子术语)
   │
   ▼  Orchestrator.run()
   │   ├─ _build_understanding()
   │   │   ├─ Synopsizer.digest_chapter(src)  → chapter.meta.source_digest  (并行)
   │   │   └─ Synopsizer.book_synopsis()      → analysis.json["book_synopsis"]
   │   │
   │   └─ 逐章 _translate_chapter():
   │       ├─ 逐批串行 _process_batch():
   │       │   ├─ RollingContext.render()  → ctx_text
   │       │   ├─ Translator.translate_batch()  → targets  (strong 档)
   │       │   ├─ Polisher.polish()  → polished  (strong 档, 可选)
   │       │   ├─ normalize_zh()  → 规范化标点
   │       │   ├─ GlossaryExtractor.extract_and_store()  → glossary.db
   │       │   └─ RollingContext.add_targets()
   │       ├─ GlossaryExtractor.extract_and_store()  (全章兜底)
   │       ├─ _review_chapter()  → review_issues  (cheap 档, 并行)
   │       ├─ _autofix_severe()  → 定向重译  (strong 档, 可选)
   │       ├─ BackTranslator.check()  → bt_issues  (fast+cheap, 抽样)
   │       └─ glossary.add_tm()  → translation_memory 表
   │
   ▼  Orchestrator._translate_titles()  (全书译完后)
   │
   ▼  Orchestrator.run_all() → run_steps({"translate","report","assemble"})
   │   ├─ ConsistencyChecker.check()  → qa_issues  (cheap 档, 可选)
   │   ├─ build_report()  → report.json
   │   └─ assemble.writer.assemble()
   │       ├─ EPUB: 按 chapter.template + Segment.anchor 回填
   │       └─ TXT:  按章 + 空行重建
   │
   ▼
output/book.zh.epub (+ book.zh-bi.epub 双语版)
```

## 状态持久化布局

所有运行态写入 `state_dir/<book-slug>/`（默认 `state/<book-slug>/`，Web UI 用 `~/.wenyi-webui/state/<book-slug>/`）：

```
state/<book-slug>/
├── manifest.json        # 书籍元信息 + 各章状态 (pending/done) + title_translated
├── chapters/
│   └── ch{n}.json       # Chapter: { index, title, segments:[Segment], href, template, meta }
├── context.json         # RollingContext.recent_targets (最多 40 段)
├── analysis.json        # 全局风格分析 + book_synopsis 全书概览
├── usage.json           # 累计 token 用量 {totals, by_tier, by_stage}
├── glossary.db          # SQLite: glossary + term_conflicts + translation_memory 三表
├── report.json          # QA 报告
└── events.jsonl         # 追加式事件日志（对账 + 续跑检查点）
```

- 所有 JSON 写入用 `tmp + os.replace` 原子替换，防写一半中断。
- `events.jsonl` 既是对账日志（含 `batch_translated` 段源/译对照、`autofix_applied` 改写前后），也是续跑检查点的数据源（`batch_glossary_extracted` 事件）。
- `glossary.db` 启用 SQLite WAL 模式 + `busy_timeout=5000`，兼顾 Web 编辑与翻译 worker 并发写。

## 两种使用入口

### 1. CLI（`trans-novel`）

`cli.py` 基于 Typer + Rich，主命令 `translate` 跑完整流水线，`resume` 等价于再次 `translate`（自动续跑），`status` 查看进度，`tools` 子命令提供细粒度调试（glossary / assemble / qa / report）。详见 [09-cli.md](09-cli.md)。

### 2. Web UI（`trans-novel-web`）

`web.py` 是 FastAPI 应用，默认监听 `127.0.0.1:8787`，静态托管 `web/dist` 前端。每个翻译任务通过 `asyncio.create_subprocess_exec` 拉起 `python -m trans_novel.app_worker` 子进程，子进程用 JSON Lines 协议向 stdout 推送 `phase` / `progress` / `completed` / `failed` 事件，`TaskManager` 解析后通过 SSE 推给前端。详见 [10-webui.md](10-webui.md)。

两种入口共享同一套 `Orchestrator` 翻译引擎，差异只在任务调度与 UI 层。

## 三档模型策略

文译将 LLM 调用分为三档（详见 [04-llm.md](04-llm.md)）：

| 档位 | 用途 | 默认模型（DeepSeek） |
|------|------|----------------------|
| `strong` | 翻译、润色、分析、定向重译、标题翻译 | `deepseek-v4-pro`（thinking=on） |
| `cheap` | 审校、一致性 QA、回译比对、语言检测 | `deepseek-v4-flash`（thinking=on） |
| `fast` | 章节梗概、全书概览归并、回译、术语抽取 | `deepseek-v4-flash`（thinking=off） |

档位回退规则（`llm/tiers.py`）：`fast` 缺则回退到 `cheap`，`cheap` 缺则回退到 `strong`，`strong` 必须存在。**永远向更便宜的方向回退**，绝不因缺档反而升到更贵的档。

## 关键设计约束汇总

| 约束 | 实现位置 | 说明 |
|------|----------|------|
| 段对齐 1:1 | `assemble/translator.py:Translator.translate_batch` | 整批 → 重试 → 逐段兜底 |
| 润色不引入漏译 | `agents/polisher.py:Polisher.polish` | 段数不符直接返回原译文 |
| 回译不阻塞 | `agents/reviewer.py:BackTranslator.check` | 回译数量不符返回 `[]` |
| 断点续跑三层粒度 | `pipeline/orchestrator.py` + `runstore.py` | 章状态 / 批术语检查点 / 批译文复用 |
| 用量增量落盘 | `llm/usage.py` + `orchestrator._flush_usage` | `_usage_checkpoint` + `usage_delta`，跨 run 不重复计费 |
| 缓存友好 | `agents/prompts.py` | system 全静态，user 静态→动态排列 |
| 原子写 | `pipeline/runstore.py:_write_json` + `web.py:_atomic_json` | `tmp + os.replace` |
| 本地安全 | `web.py:reject_cross_site_writes` | POST/PUT/PATCH/DELETE 校验 Origin |
