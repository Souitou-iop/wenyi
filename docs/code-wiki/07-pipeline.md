# 07 · 流水线编排与状态机（pipeline）

`pipeline` 模块是文译的全局编排者。`Orchestrator` 驱动章级状态机与断点续跑，`RunStore` 负责原子持久化，`RollingContext` 维护滚动上下文，`checks` 提供零成本的第一道校验。

## 文件：`pipeline/orchestrator.py` — 编排器

### 设计要点

> 单章流水线（章内批次**串行**，逐批刷新滚动上下文与术语快照；跨章亦串行传递梗概）：
> - 每批：渲染上下文（含前一批刚译出的译文）→ 翻译（对齐保证）→ 润色（可选）→ 标点规范化 → 术语/称呼/固定表达实时抽取入库 → 立即供下一批参照。
> - 章末：全章术语兜底抽取 → 整章分块并行审校 → 严重项串行定向重译（`autofix_severe`，过长度校验才采纳）→ 回译抽检 → 写 TM → 落盘标记 done。
>
> 翻译前先预扫源文建立全书理解（逐章梗概+全书概览，fast 档并行），作恒定前缀注入每章翻译。

### 关键类型

```python
ProgressFn = Callable[[int, int, str], None]   # (done, total, label)
PhaseFn    = Callable[[str, str], None]        # (phase_id, phase_label)

@dataclass
class _BatchResult:
    targets: list[str]
    issues: list[dict] = field(default_factory=list)
    bt_samples: list[tuple[str, str]] = field(default_factory=list)

ALL_STEPS = ("translate", "qa", "report", "assemble")
_SEVERE_TYPES = ("missing", "mistranslation")  # 触发章末自动重译的严重问题类型
```

### `_LANG_ALIASES` 与 `_normalize_lang`

把"日语/japanese/jpn/jp"等多种写法归一化为 ISO 639-1 两字母代码；`auto/unknown/mixed/多语言/未知` 等返回空串。

### `Orchestrator` 类

```python
class Orchestrator:
    def __init__(self, config: Config, client: LLMClient | None = None)
```

构造时：
- `self.client = client or build_client(config)`
- `self._usage_checkpoint = self.client.usage_summary()`（用量增量落盘基线）
- 同时实例化 7 个 agent（全部共享同一个 `self.client`）：
  `Analyzer` / `Synopsizer` / `Translator` / `Reviewer` / `BackTranslator` / `Polisher` / `GlossaryExtractor`。

### 用量落盘

```python
def _flush_usage(self, store: RunStore, *, scope: str) -> dict[str, Any]
```
把 client 自上次 checkpoint 以来的增量合并到 `usage.json`，并 `log_event("usage_summary", scope, increment, cumulative)`。增量全 0 时不落盘但仍返回 cumulative。详见 [04-llm.md](04-llm.md#增量落盘机制)。

### 语言应用

```python
def _apply_language(self, lang: str) -> None
```
把解析出的源语言写回 `config.source_lang` 并同步到 7 个 agent 的 `.src`。

### 准备 / 续跑入口

```python
def prepare(self, input_path: str, *, progress: Optional[ProgressFn] = None) -> RunStore
```

流程：
1. `load_document` 解析源文件（超长段按 `max_chars_per_segment` 拆，续段标 `cont`）。
2. `run_dir = state_dir/<slug(title)>`；若已存在 manifest → 续跑，直接返回（语言在 `run()` 里按 manifest 应用）。
3. 新建：`source_lang` 为 auto 时调 `_detect_language_ai`（cheap 档、`stage="language_detect"`）；失败抛 `RuntimeError` 要求显式指定。
4. `store.init_from_document(doc)` 写 manifest + 各章。
5. `Analyzer.analyze(sample)` 做全书风格分析（多点采样：开头/中部/结尾各一段）→ `seed_glossary` → `save_analysis`。
6. `save_context(RollingContext().to_dict())` 初始化空上下文。

```python
def _detect_language_ai(self, doc) -> str
```
取单段纯源文前 1500 字符，要求模型仅输出 `{"language":"<ISO>"}`，归一化后返回。**labeled=False** 防多点采样的中文标签污染语言检测。

```python
@staticmethod
def _sample_text(doc, *, labeled: bool = True) -> str
```
- `labeled=True`：多点采样（开头/中部/结尾各一段，带"【开头样章】"等中文标签），让分析覆盖全书风格全貌。
- `labeled=False`：返回单段纯源文（语言检测用，不能混入中文标签）。

### 主翻译入口

```python
def run(self, input_path: str, *, only_chapter: int | None = None,
        progress: Optional[ProgressFn] = None,
        phase: Optional[PhaseFn] = None) -> RunStore
```

流程：
1. `prepare` → `apply_language` → 加载 glossary/context/style。
2. `_build_understanding` 预扫全书生成逐章梗概 + 全书概览（注入各章翻译 prompt）。
3. 取待译章（`only_chapter` 或 `store.pending_chapters()`）。
4. 逐章 `_translate_chapter`，每章后 `save_context` + `_flush_usage(scope="chapter")`。
5. 全书译完后 `_translate_titles`（书名保持原文，章节标题与目录项译成中文写回 manifest）。
6. finally 块 `glossary.close()` + `_flush_usage(scope="translate")`。

```python
def _progress_counts(self, store: RunStore, chapter_indices: list[int]) -> tuple[int, int]
```
按全书批次检查点算 (total, done)；**只有整批译文齐全才计入 done**，不完整批次整体重跑（避免提前计入个别已有段导致重复累加）。

### 全书理解预扫

```python
def _build_understanding(self, store: RunStore,
                         progress: Optional[ProgressFn] = None) -> str
```

- 关闭 `book_understanding` 时直接返回空串。
- 各章梗概相互独立 → `ThreadPoolExecutor(max_workers=prescan_concurrency)` 并行调 `synopsizer.digest_chapter`；**落盘全部在主线程**，逐章增量保存，续跑粒度不变。
- 已有 `source_digest` 的章跳过（幂等）。
- 各章梗概归并出 `book_synopsis`（仅当不存在且至少一章有梗概时调 `synopsizer.book_synopsis`），存入 `analysis.json`，`log_event("book_synopsis_saved")`。

### 章节标题翻译

```python
def _translate_titles(self, store: RunStore, glossary: GlossaryStore,
                      progress: Optional[ProgressFn] = None) -> None
```

把章节标题与 toc_entries（排除已是章节 href 的项）压成单行，批量调 `strong` 档翻译，`stage="title_translate"`；写回 manifest 的 `title_translated` 字段。**书名不译**，借术语表保证专名一致。已全部译过则跳过（幂等）。返回段数与预期不符 → `log_event("titles_translation_rejected", reason="count_mismatch")`。

### 单章流水线

```python
def _translate_chapter(self, ci: int, store: RunStore,
                       glossary: GlossaryStore, context: RollingContext,
                       style: str, book_synopsis: str = "", *,
                       progress: Optional[ProgressFn] = None,
                       done: int = 0, total: int = 0) -> int
```

步骤：
1. `load_chapter` → 取 `text_segments`；空章直接 `set_chapter_status(done)`。
2. `chapter_digest = chapter.meta.get("source_digest")`（预扫产物）。
3. `batch_segments(text_segs, max_chars_per_batch)` 分批。
4. `glossary_checkpoints = store.completed_batch_glossary_keys(ci)` 恢复已抽术语的批次集合。
5. `term_snapshot = _chapter_term_snapshot(glossary, text_segs)`：按 `glossary_scope`（chapter/full）裁剪注入术语。
6. **逐批串行**（换取章内跨批的代词/术语/语气连贯）：
   - **断点续跑**：若该批所有段已有非空 target → 复用译文，`context.add_targets` 重建上下文后跳过；术语按 `glossary_key` 是否在 checkpoints 决定是否重抽；`log_event("batch_skipped", reason="already_translated")`。
   - 否则：`ctx_text = context.render(rolling_context_segments)` → `_process_batch` → 写回 `s.target` → `log_event("batch_translated", segments=[...])` → `context.add_targets(targets)` → 累计 issues/bt_samples → `done += len(b)` → `chapter.meta["review_issues"] = review_issues` → `save_chapter` → **译文落盘后再抽术语**（避免中断时术语库领先章节产物） → `glossary_checkpoints.add(glossary_key)` → 刷新 term_snapshot。
7. **章末全章术语兜底抽取**：`extractor.extract_and_store(glossary, src_text, tgt_text, ci)`（捕捉跨段才能确认的称呼/口癖）。
8. **章末审校**（若 `pipeline.review`）：清旧 review_issues（防续跑重入重复累积）→ `_review_chapter` 分块并行 → 若 `autofix_severe` → `_autofix_severe` 串行定向重译 → 标记 `stage="review"`、`fixed` 字段。
9. **回译抽检**：对 `_process_batch` 里按 `backtranslate_sample` 概率抽样的 `(src, tgt)` 调 `backtrans.check`。
10. **写翻译记忆库**：`glossary.add_tm(s.source, s.target, ci)`（仅记录，不跨位置复用）。
11. `chapter.meta["review_issues"] / ["backtranslation_issues"]` → `save_chapter` → `set_chapter_status(done)` → `log_event("chapter_done")`。

### 辅助方法

```python
def _chapter_term_snapshot(self, glossary: GlossaryStore, text_segs) -> list
```
`glossary_scope != "chapter"` 返回全表；否则用 `GlossaryStore.terms_in(terms, src_text)` 只留本章命中的词条（省 token）。

```python
def _extract_batch_glossary(self, glossary, store, chapter, start_index, batch) -> dict[str, int]
```
批级术语抽取 + `log_event("batch_glossary_extracted", summary)`。

### 章末审校

```python
def _review_chapter(self, text_segs, terms) -> list[dict]
```

- `budget = max_chars_per_batch * 3`（约 3 倍翻译批大小，减少调用次数与重复注入的输入 token）。
- `_pack_contiguous(segs, budget)`：按源文字符预算保序打包成连续块。
- 每块调 `reviewer.review(srcs, tgts, terms)`，返回的 `index` 是块内下标，加块首段偏移映射回章内段号；**越界 index 直接丢弃**（防模型幻觉）。
- `workers = min(review_concurrency, len(jobs))`；`workers == 1` 串行，否则 `ThreadPoolExecutor.map` 保持输入顺序（结果确定性）。

```python
@staticmethod
def _pack_contiguous(segs, budget: int) -> list[list]
```
按源文字符预算把段保序打包成若干连续块。

### 严重项定向重译

```python
def _autofix_severe(self, text_segs, issues, terms, style,
                    book_synopsis: str = "", chapter_digest: str = "", *,
                    store: RunStore | None = None,
                    chapter_index: int | None = None) -> None
```

- 只处理 `type in ("missing", "mistranslation")` 的严重项，按段聚合。
- **每段最多重译一次**；用该段前后各 2 段译文做局部上下文（章末重译时原滚动上下文已失效）。
- 调 `translator.retranslate_with_feedback(...)`。
- **采纳条件**：重译非空且过 `checks.length_flags` 校验。采纳则 `normalize_zh` 后更新 `seg.target`，标 `fixed=True`，`log_event("autofix_applied")`；不采纳保持 `fixed=False` 留人工，`log_event("autofix_rejected")`。

### 单批处理

```python
def _process_batch(self, batch, terms, ctx_text: str, style: str,
                   book_synopsis: str = "", chapter_digest: str = "") -> _BatchResult
```

1. `translator.translate_batch(sources, glossary_terms=terms, style=style, context=ctx_text, book_synopsis, chapter_digest)`。
2. 若 `pipeline.polish`：`polisher.polish(targets, ...)`，长度一致才采纳。
3. 若 `punctuation_normalize`：`normalize_zh` 每段。
4. 若 `backtranslate_sample > 0`：按概率抽样 `(src, tgt)` 用于章末回译。
5. 返回 `_BatchResult(targets, issues=[], bt_samples)`。**LLM 审校不在批内做**（移到章末）。

### 步骤子集 / 全流程

```python
def run_steps(self, input_path: str, steps, *,
              progress: Optional[ProgressFn] = None,
              phase: Optional[PhaseFn] = None,
              out_format: str = "epub", out_path: str | None = None) -> dict[str, Any]
```

- `steps ⊆ ALL_STEPS = ("translate", "qa", "report", "assemble")`。
- 含 `translate` → 调 `self.run`；否则只 `prepare` + `apply_language`。
- 含 `qa` → `ConsistencyChecker(client, config).check(store, glossary)` → `log_event("consistency_qa_finished")`。
- 含 `report` → `build_report(store, glossary)`，`report["consistency_issues"] = qa_issues`，`store.save_report`。
- 含 `assemble` → 按 `output.mono/bilingual` 调 `assemble(...)` 生成单语/双语 EPUB；都关时兜底产单语。
- 返回 `{store, output, outputs, report, qa_issues}`。

```python
def run_all(self, input_path: str, *, progress=None, phase=None,
            out_format="epub", out_path=None, do_qa=None) -> dict[str, Any]
```
translate + report + assemble，按 `do_qa` 或 `pipeline.consistency_qa` 决定是否加 qa。

## 文件：`pipeline/runstore.py` — 状态持久化

### 目录布局

```
state/<book-slug>/
├── manifest.json        # 书籍元信息 + 各章状态 (pending/done) + title_translated
├── chapters/
│   └── ch{n}.json       # Chapter: {index, title, segments:[Segment], href, template, meta}
├── context.json         # RollingContext.recent_targets (最多 40 段)
├── analysis.json        # 全局风格分析 + book_synopsis
├── usage.json           # 累计 token 用量 {totals, by_tier, by_stage}
├── glossary.db          # SQLite（由 GlossaryStore 管理，不在本模块）
├── report.json          # QA 报告
└── events.jsonl         # 追加式事件日志（对账 + 续跑检查点）
```

### 关键常量

```python
STATUS_PENDING = "pending"
STATUS_DONE = "done"
```

### 辅助函数

```python
def slugify(name: str) -> str
```
把书名转成目录安全的 slug，保留中文/日文/韩文范围字符，其余非单词字符替换为 `_`，空结果回退为 `"book"`。

### `RunStore` 类

```python
class RunStore:
    def __init__(self, run_dir: str, *, create: bool = True)
    def ensure_dirs(self) -> None          # makedirs chapters_dir
    # 路径属性：manifest_path / context_path / analysis_path / glossary_path /
    #           report_path / usage_path / event_log_path / chapter_path(ci)
    def exists(self) -> bool               # manifest 是否存在
```

#### 通用 JSON 读写（原子写）

```python
@staticmethod
def _write_json(path, data)   # 写 path.tmp 后 os.replace 原子替换
@staticmethod
def _read_json(path)
```

#### manifest 操作

```python
def init_from_document(self, doc: Document) -> dict
    # 写 manifest（title/fmt/source_path/langs/meta/chapters[index,title,href,status=pending]）
    # 同时把每章写 chapters/ch{n}.json
def save_manifest(self, manifest) -> None
def load_manifest(self) -> dict
def set_chapter_status(self, ci, status) -> None
def pending_chapters(self) -> list[int]   # status != done 的章序号
```

#### 章节操作

```python
def save_chapter(self, chapter: Chapter)   # 写 chapters/ch{index}.json
def load_chapter(self, ci) -> Chapter
```

#### 上下文/分析/报告/用量

```python
def save_context(data) / load_context() -> dict | None
def save_analysis(data) / load_analysis() -> dict | None
def save_report(data)
def save_usage(data) / load_usage() -> dict | None
```

### 批次恢复检查点（关键续跑机制）

```python
@staticmethod
def batch_glossary_key(start_index: int, count: int) -> str   # 返回 "start:count"
def completed_batch_glossary_keys(self, chapter: int) -> set[str]
```

- `batch_glossary_key` 把"批首段章内序号 + 批段数"编码成检查点键，**批次边界变化时不会误命中旧键**。
- `completed_batch_glossary_keys` 扫描 `events.jsonl` 里所有 `event == "batch_glossary_extracted"` 的行，恢复出本章已抽过术语的批次集合。结果按章缓存在 `self._batch_glossary_event_cache: dict[int, set[str]] | None`，**每个 RunStore 实例最多扫一次**。
- `log_event` 在写 `batch_glossary_extracted` 时同步更新缓存，避免重复扫描。

### 追加式事件日志

```python
def log_event(self, event: str, **data: Any) -> None
```

- 每条事件 = `{ts: ISO 本地时间(秒级), event: str, **data}`。
- 以 `sort_keys=True` + `ensure_ascii=False` 追加一行 JSONL 到 `events.jsonl`。
- 既是对账日志（翻译行为、改写前后、产物），也是续跑检查点的数据源（批次术语抽取）。

## 文件：`pipeline/context.py` — 滚动上下文

### 设计哲学

滚动上下文只负责"最近译文"这段每批变化的**局部尾巴**，用于代词指代/称谓/语气衔接。全局/前瞻理解改由翻译前的源文预扫提供（`agents/synopsis.py`）：【全书概览】（全程恒定）+【本章梗概】（每章恒定）作为稳定前缀注入翻译 prompt，二者互补。

### `RollingContext`

```python
@dataclass
class RollingContext:
    recent_targets: list[str] = field(default_factory=list)
    max_recent_keep: int = 40     # 最多保留多少段尾部译文
```

#### 方法

- **`render(n_recent: int) -> str`**：返回最近 `n_recent` 段译文（纯文本，无标题），`n_recent <= 0` 返回空。实际注入的段数由 `Config.pipeline.rolling_context_segments` 控制（默认 6）。
- **`add_targets(targets)`**：扩展 `recent_targets`（跳过空/空白），超过 `max_recent_keep` 时只保留尾部 40 段（滑动窗口）。
- **`to_dict() / from_dict()`**：序列化为 `{recent_targets: [...]}`，存入 `context.json` 供断点续跑。

### 与 Orchestrator 的协作

- 章内逐批串行：每批翻译前 `ctx_text = context.render(rolling_context_segments)` 注入；翻译后 `context.add_targets(res.targets)` 立即更新，供下一批参照。
- 跨批续跑：若该批已有译文，`context.add_targets(existing_targets)` 重建上下文后跳过。
- 章末保存：每章结束 `store.save_context(context.to_dict())`。
- 章末 autofix 时原滚动上下文已失效，改用该段前后各 2 段译文做局部上下文（在 `_autofix_severe` 里直接读 `text_segs`）。

## 文件：`pipeline/checks.py` — 廉价校验

无 LLM、零 token 成本的第一道校验。

### 关键数据结构

```python
@dataclass
class LengthFlag:
    index: int
    ratio: float
    reason: str   # "too_short" | "too_long" | "empty"
```

### 主要函数

```python
def count_aligned(sources, targets) -> bool
```
段数是否一致（最硬的整段漏译防线）。

```python
def length_flags(sources, targets, *, too_short=0.30, too_long=3.0) -> list[LengthFlag]
```
按"译文/原文"字符比标记可疑段：
- 原文为空跳过。
- 译文为空 → `empty`。
- ratio < 0.30 → `too_short`（多半漏译）。
- ratio > 3.0 → `too_long`（可能失控/增译）。
- 阈值偏宽松，只抓明显异常，避免误报。

被 `Orchestrator._autofix_severe` 用于决定是否采纳重译结果。

## 断点续跑三层粒度总结

| 粒度 | 机制 | 实现位置 |
|------|------|----------|
| **章级** | `manifest.chapters[*].status` ∈ {pending, done} | `RunStore.pending_chapters()` |
| **批级（术语检查点）** | `events.jsonl` 里每条 `batch_glossary_extracted` 记录 `{chapter, start_index, count}`，编码为 `"start:count"` 键 | `RunStore.completed_batch_glossary_keys` |
| **批级（译文复用）** | 检查每批所有段是否都有非空 `target`，是则整批跳过、不重翻，只重建滚动上下文 | `Orchestrator._translate_chapter` |

**关键设计**：只有整批译文齐全才计入 done 与跳过；不完整批次整体重跑，避免提前计入个别已有段导致重复累加。
