# 05 · 翻译 Agent 体系（agents）

`agents` 模块定义文译的所有"智能体"。每个 Agent 负责流水线的一个具体环节（分析/翻译/审校/润色/一致性 QA），通过共享的 `LLMClient` 调用模型，按 `stage=type(self).__name__` 归因 token 用量。

> 注意：`GlossaryExtractor`（术语抽取）虽然继承 `Agent`，但位于 `glossary/extractor.py`，详见 [06-glossary.md](06-glossary.md)。`Translator` 的真实实现在 `assemble/translator.py`，`agents/translator.py` 仅是兼容性 re-export。

## 文件：`agents/base.py` — Agent 基类

```python
_RAISE = object()  # 哨兵：区分"未提供 default"与"default 为 None"

class Agent:
    def __init__(self, client: LLMClient, config: Config):
        self.client = client
        self.config = config
        self.src = config.source_lang   # 被 orchestrator._apply_language 写回
        self.tgt = config.target_lang

    def _ask_json(self, system: str, user: str, *, tier: str,
                  key: str | None = None, default: Any = _RAISE,
                  max_tokens: int | None = None) -> Any

    def _ask_text(self, system: str, user: str, *, tier: str,
                  default: str = "", max_tokens: int | None = None) -> str

    @staticmethod
    def dict_items(items: Any) -> list[dict]
```

### 职责

不承担业务，仅为所有 agent 提供：
- 构造统一化（`client` / `config` / `src` / `tgt`）。
- LLM 调用帮助（含异常回退）。
- 列表清洗工具。

### 关键方法说明

**`_ask_json`**：渲染 system/user → `client.complete_json(..., stage=type(self).__name__)`。异常处理：若 `default is _RAISE` 则照常抛出；否则返回 default。`key` 给出时：结果为 dict 取 `data[key]`（缺失回退到 default）；结果为非空 list 直接返回；否则回退到 default。这是各 agent "渲染 prompt → complete_json → 失败回退默认值"模式的统一收敛点。

**`_ask_text`**：调 `client.complete(...)` 取纯文本并 strip；异常时返回 default。专供不需要 JSON 的机械任务（如梗概生成）。

**`dict_items`**：从任意输入中过滤出 dict 元素，用于清洗模型返回的 issues/terms 列表（防模型幻觉返回非 dict）。

### `.src` 契约

`orchestrator._apply_language` 直接写每个 agent 的 `.src` 属性。基类把该契约显式化——所有 agent 都有 `.src`，运行期 auto 检测后会统一更新。

## 文件：`agents/analyzer.py` — Analyzer

```python
class Analyzer(Agent):
    def analyze(self, sample_text: str) -> dict[str, Any]
    def seed_glossary(self, store: GlossaryStore, analysis: dict[str, Any]) -> int
    def style_brief(self, analysis: dict[str, Any]) -> str
```

### 流水线位置

**prepare 阶段**（前期准备）。通读样章后产出全书统一基准。

### 方法说明

- **`analyze(sample_text)`**：渲染 `analyzer_system` / `analyzer_user` prompt（注入 `src`/`tgt`/`sample`），用 **strong 档**调模型返回 JSON。**不传 default**（分析失败要显式暴露给调用方）。对返回结果做字段补全：`genre`、`tone`、`style_guide`、`narration`、`pacing`、`register`、`dialogue_style`、`rhetoric`、`characters`、`terms`。
- **`seed_glossary(store, analysis)`**：把 analysis 里 `characters`（角色）与 `terms`（术语）种入术语库。角色条目用 `TYPE_PERSON` 类型，`first_chapter=0` 表示全书基准；术语条目用 analysis 给的 `type`。返回写入条目数。空 source/target 跳过。
- **`style_brief(analysis)`**：把 analysis 浓缩成给译者注入的中文风格/角色简报文本（体裁、语气文体、风格指南、5 个细粒度风格维度、角色列表）。对旧 `analysis.json` 缺字段自动跳过（向后兼容）。

### 协作

- 被 `Orchestrator.prepare` 调用：`analyze(sample)` → `seed_glossary(glossary, analysis)` → `save_analysis(analysis)`。
- 产出的 `analysis` 被 `style_brief` 二次消费，作为 translator/polisher 的 `style` 参数。
- 也作为 `Synopsizer.book_synopsis` 的 `analysis_brief` 输入。

## 文件：`agents/synopsis.py` — Synopsizer

```python
class Synopsizer(Agent):
    def digest_chapter(self, source_text: str) -> str
    def book_synopsis(self, digests: list[str], analysis_brief: str) -> str
    @staticmethod
    def _group(items: list[str], budget: int) -> list[list[str]]
    def _synth(self, digests: list[str], analysis_brief: str) -> str
```

模块级常量：`_REDUCE_BUDGET = 12000`（归并时单次喂入的各章梗概字符预算）。

### 流水线位置

**翻译前的全书理解预扫阶段**（fast 档）。通读源文，产出：
- **逐章梗概**（chapter digest）：每章一段中文梗概，存入 `chapter.meta["source_digest"]`。
- **全书概览**（book synopsis）：把各章梗概 + 前期分析归并成一份全局概览，存入 `analysis.json["book_synopsis"]`。

二者作为**恒定前缀**注入翻译 prompt（见 `prompts.TRANSLATOR_USER` 的 `$book_synopsis` 与 `$chapter_digest` 占位），让译者翻任意章节前都"对全书有理解"，把握主线走向、人物弧光、伏笔与谜底。全局块全程不变，命中前缀缓存近免费复用。

### 方法说明

- **`digest_chapter(source_text)`**：空文本返回 `""`。渲染 `chapter_digest_system` / `chapter_digest_user`（注入 `source=source_text[:8000]`，截断防超长）。用 **fast 档**调 `_ask_text`，`max_tokens=600`（梗概 ≤200 字，留裕量防输出失控）。
- **`book_synopsis(digests, analysis_brief)`**：先过滤空梗概；空则返回 `""`。循环：用 `_group` 按字符预算贪心打包；只有一组直接 `_synth` 返回；多组则每组先 `_synth` 归并成较粗概览，再进入下一轮归并（map-reduce 思想，避免单次 prompt 超长）。
- **`_group(items, budget)`**：贪心打包，每组 joined 长度尽量 ≤ budget。
- **`_synth(digests, analysis_brief)`**：把一组梗概编号拼接，渲染 `book_synopsis_system` / `book_synopsis_user`，用 **fast 档**调 `_ask_text`，`max_tokens=1200`（概览 ≤500 字）。

### 协作

- 被 `Orchestrator._build_understanding` 调用：多线程并发 `digest_chapter`（`prescan_concurrency` 控制），落盘全部在主线程逐章保存；归并 `book_synopsis(digests, Analyzer.style_brief(analysis))` 写回 `analysis`。
- 产出的 `book_synopsis` 与 `chapter_digest` 通过 `Translator.translate_batch` 参数注入翻译 prompt。

## 文件：`assemble/translator.py` — Translator（核心）

> `agents/translator.py` 只是兼容包装：`from ..assemble.translator import AlignmentError, Translator`。

```python
class AlignmentError(Exception): ...

class Translator(Agent):
    def _call_batch(self, sources, glossary_terms, style, context,
                    book_synopsis="", chapter_digest="") -> list[str]
    def _translate_one(self, source, glossary_terms, style, context,
                       book_synopsis, chapter_digest) -> str
    def retranslate_with_feedback(self, source, *, feedback,
                                  glossary_terms=None, style="",
                                  context_before="", context_after="",
                                  book_synopsis="", chapter_digest="") -> str
    def translate_batch(self, sources, *, glossary_terms=None, style="",
                        context="", book_synopsis="", chapter_digest="") -> list[str]
```

### 流水线位置

**每章翻译阶段的核心**（strong 档）。

### 核心保证：句段对齐

输入 N 段，输出必须是 N 段译文，一一对应。**三级策略**：
1. 整批翻译（`_call_batch`）。
2. 段数不符重试 `align_retry_limit + 1` 次。
3. 逐段兜底（`_translate_one`）。

从结构上保证 1:1，杜绝整段漏译。

### 方法说明

- **`_call_batch`**（内部）：渲染 `translator_system`（注入 `n`、显式覆盖 `lang_guidance` 为带 `config.honorific_strategy` 的版本）与 `translator_user`（注入 `style`/`book_synopsis`/`glossary`/`chapter_digest`/`context`/`n`/`n_minus_1`/`numbered_source`）。用 **strong 档**调 `_ask_json`，`key="translations"`，**不传 default**（失败照常抛出，由 `translate_batch` 处理）。返回的 list 元素强转 str；非 list 抛 `AlignmentError`。
- **`_translate_one`**（内部）：对单段调用 `_call_batch([source], ...)`，返回首元素或空串。用于段数对齐失败的兜底。
- **`retranslate_with_feedback`**（公开）：带审校意见定向重译单段（章末 autofix 用）。复用 `translator_system`（与主翻译共享稳定前缀命中缓存），user 用 `translator_fix_user`：前缀块与主翻译一致，上下文换成 `context_before` + `context_after`，附 `feedback`。用 **strong 档**调，`key="translations"`，default 为 `None`。返回 `str(items[0]).strip()` 或空串。
- **`translate_batch`**（公开核心）：空列表返回 `[]`。流程：
  1. `attempts = config.pipeline.align_retry_limit + 1` 次循环尝试 `_call_batch`；
  2. 任何异常都吞掉置 `out=[]`；
  3. 段数等于 `n` 立即返回；
  4. 重试耗尽后兜底：逐段 `_translate_one`。

### 协作

- 被 `Orchestrator._process_batch` 调用主翻译。
- 被 `Orchestrator._autofix_severe` 调用定向重译（feedback 来自 `Reviewer.review` 的 issues）。
- 输入：`style` ← `Analyzer.style_brief`；`book_synopsis` ← `Synopsizer.book_synopsis`；`chapter_digest` ← `Synopsizer.digest_chapter`（存于 `chapter.meta["source_digest"]`）；`glossary_terms` ← `GlossaryStore`；`context` ← `RollingContext`。
- 输出：targets 被 `Reviewer.review` 审校、`BackTranslator.check` 抽检、`Polisher.polish` 润色。

## 文件：`agents/polisher.py` — Polisher

```python
class Polisher(Agent):
    def polish(self, targets: list[str], *,
               glossary_terms: list[GlossaryTerm] | None = None,
               style: str = "") -> list[str]
```

### 流水线位置

**每章翻译→审校之后的润色阶段**（strong 档）。

### 方法说明

- **`polish`**：空列表直接返回 `[]`。渲染 `polisher_system`（注入 `n`，**system 内不含每批变化的量以命中前缀缓存**）和 `polisher_user`（注入 `glossary`、`style`、`n`、`numbered_target`）。用 **strong 档**调用，`key="polished"`，default 为 `None`。**对齐校验**：仅当返回是 list 且长度等于 `n` 时才采用，否则保守返回原 `targets` 列表（绝不因润色而引入漏译）。

### 硬约束

- 不增删信息。
- 保持段数不变，与输入一一对应。
- 对齐失败时保留原译文。

### 协作

被 `Orchestrator._process_batch` 调用：`polished = self.polisher.polish(targets, ...)`；长度匹配才替换 `targets`。

## 文件：`agents/reviewer.py` — Reviewer + BackTranslator

### `Reviewer`

```python
class Reviewer(Agent):
    def review(self, sources: list[str], targets: list[str],
               glossary_terms=None) -> list[dict[str, Any]]
```

#### 流水线位置

**每章翻译后的审校阶段**（cheap 档）。

#### 方法说明

- **`review`**：空 sources 直接返回 `[]`。渲染 `reviewer_system` 与 `reviewer_user`（注入 `glossary`、`n`、`pairs=numbered_pairs(sources, targets)`）。用 **cheap 档**调用，`key="issues"`，default 为 `[]`，再用 `dict_items` 清洗。返回 issue 列表，形如：
  ```python
  {"index": int, "type": "missing|added|mistranslation|terminology|pronoun",
   "detail": str, "suggestion": str}
  ```
  prompt 强调"拿不准就不报，宁缺毋滥"。

#### 协作

- 被 `Orchestrator._review_chapter` 在 chunk 维度并发调用（`review_concurrency` 控制）。
- 产出的 issues 喂给 `Translator.retranslate_with_feedback` 做 autofix（同段 issues 拼成 feedback 字符串）。

### `BackTranslator`

```python
class BackTranslator(Agent):
    def backtranslate(self, targets: list[str]) -> list[str]
    def check(self, sources: list[str], targets: list[str]) -> list[dict[str, Any]]
```

#### 流水线位置

**审校之后的回译抽检阶段**。

#### 方法说明

- **`backtranslate(targets)`**：空列表返回 `[]`。渲染 `backtranslate_system` / `backtranslate_user`（注入 `n`、`numbered_target`）。用 **fast 档**调用（机械回译免思考），`key="backtranslations"`，default 为 `[]`。返回字符串列表，非 list 时返回 `[]`。
- **`check(sources, targets)`**：对给定（已抽样的）段做"回译 + 比对"两步。先 `backtranslate(targets)`；若回译数量与 sources 不一致则直接返回 `[]`（对齐失败不阻塞）；否则把"原文 vs 回译"拼成 pairs，用模块级 `_backtrans_compare_system(self.src)` 作 system，用 **cheap** 档调 `_ask_json`，`key="issues"`，default 为 `[]`。返回形如 `{"index": int, "detail": str}` 的偏离问题列表。

### `_backtrans_compare_system(src)`

模块级函数，动态拼接回译比对 system prompt。让模型判断"原文 vs 译文回译"语义是否一致，只报实质性偏离，输出 `{"issues":[{"index","detail"}]}`。

## 文件：`agents/consistency.py` — ConsistencyChecker

```python
class ConsistencyChecker(Agent):
    @staticmethod
    def _chapter_label(title: str, index: int) -> str
    def _chapter_digests(self, store: RunStore, max_chars_each: int = 600) -> str
    def check(self, store: RunStore, glossary: GlossaryStore) -> list[dict[str, Any]]
```

### 流水线位置

**全书翻译完成后的跨章一致性 QA 阶段**（cheap 档）。

### 方法说明

- **`_chapter_digests`**：从 `RunStore` 加载 manifest，遍历 `STATUS_DONE` 章节；每章取首 3 段 + 末 2 段译文，拼成 `head……tail` 形式并截断到 600 字符；用章节标签 + snippet 拼成多章摘要文本。控制 token 用量。
- **`check`**：若没有摘要直接返回 `[]`。否则渲染 `consistency_system`，user 拼接"专有名词对照表（来自 `glossary.all_terms()` 经 `prompts.render_glossary` 渲染）+ 各章译文摘要"，要求模型输出 `{"issues":[...]}`。用 **cheap 档**调用，`key="issues"`，default 为 `[]`。最后用 `dict_items` 过滤。返回的 issue 形如：
  ```python
  {"type": "terminology|pronoun|tone|punctuation", "detail": "...", "where": "章节线索"}
  ```

### 协作

- 被 `Orchestrator.run_steps` 在 QA 阶段实例化调用：`ConsistencyChecker(self.client, self.config).check(store, glossary)`。
- 也被 CLI 直接调用（`cli.py` 的 `tools qa` 子命令）。

## 文件：`agents/prompts.py` — 提示词模板

无类。包含多个 `string.Template` 实例和几个渲染辅助函数。用 `string.Template` 的 `$` 占位（避免与 JSON 示例里的花括号冲突）。

### 关键函数

```python
def render(name: str, *, src: str = "ja", tgt: str = "zh", **kwargs) -> str
def honorific_rule(strategy: str) -> str  # 兼容包装，委托 langprofile
def render_glossary(terms: list[GlossaryTerm]) -> str
def numbered(texts: list[str]) -> str
def numbered_pairs(sources: list[str], targets: list[str]) -> str
```

### `render`

按 name 从 `_DEFAULTS` 字典取出 `Template`，自动按 `src` 注入默认占位（`src_label`/`lang_guidance`/`term_guidance`/`punct_rule`，均来自 `langprofile` 与 `PUNCT_RULE`），调用方可通过同名 kwarg 覆盖。用 `safe_substitute` 渲染（避免缺占位报错）。

### 模板清单（`_DEFAULTS` 的 key）

| 模板 key | 消费者 |
|----------|--------|
| `translator_system` / `translator_user` / `translator_fix_user` | `Translator` |
| `reviewer_system` / `reviewer_user` | `Reviewer` |
| `polisher_system` / `polisher_user` | `Polisher` |
| `title_translator_system` / `title_translator_user` | `Orchestrator._translate_titles` |
| `analyzer_system` / `analyzer_user` | `Analyzer` |
| `glossary_extractor_system` / `glossary_extractor_user` | `GlossaryExtractor` |
| `backtranslate_system` / `backtranslate_user` | `BackTranslator` |
| `consistency_system` | `ConsistencyChecker` |
| `chapter_digest_system` / `chapter_digest_user` | `Synopsizer.digest_chapter` |
| `book_synopsis_system` / `book_synopsis_user` | `Synopsizer.book_synopsis` |

### 缓存友好约定

模块文档注释强调 DeepSeek 前缀缓存约定：
- **system 模板必须全静态**（一次运行内恒定），段数等每批变化的量写在 user 末尾。
- **user 模板按"静态→动态"排列**：风格指南/全书概览 → 本章梗概 → 术语表 → 前文译文 → 待译正文。
- 以最大化前缀缓存命中。

### `render_glossary`

把术语条目列表渲染成中文人类可读的对照表文本。每条形如 `- source → target（type，gender，读音:xxx）[别名: ...]`。空列表返回"（暂无）"。

### `numbered` / `numbered_pairs`

- `numbered`：渲染成 `[0] xxx\n[1] yyy` 形式。
- `numbered_pairs`：渲染成逐段对照 `[i] 原文：xxx\n    译文：yyy`。

## 文件：`agents/langprofile.py` — 语言相关辅助

无类，纯函数模块。导出常量 `LABELS`（语言代码 → 中文标签）和四个函数。

```python
def label(src: str) -> str
def honorific_rule(strategy: str) -> str
def translate_guidance(src: str, honorific_strategy: str = "keep_style") -> str
def term_guidance(src: str) -> str
```

### 方法说明

- **`label(src)`**：ISO 639-1 → 中文标签（如 `ja→日文`、`en→英文`）；未知回退 `f"{src}文"`；空返回"原文"。
- **`honorific_rule(strategy)`**：返回中文规则文本。三种策略：
  - `keep_style`：保留语气并全书统一（如 先輩→前辈、ちゃん→小X）。
  - `normalize`：统一规则处理。
  - `drop`：不影响语义时省略。
- **`translate_guidance(src, honorific_strategy)`**：返回翻译/润色用的源语言相关译法要点。对 `ja` 给出敬称、第一人称代词、拟声拟态词、汉字词处理 4 条；对 `en` 给出称谓、人称性别、时态从句、专有名词译名 4 条；其他语言回退通用文本。
- **`term_guidance(src)`**：返回分析/术语抽取用的 reading 字段与性别判断说明。`ja` 要求填假名读音并依第一人称判断性别；`en` 要求 reading 留空、依姓名常识判断性别。

### 协作

被 `prompts.render` 调用注入默认占位；被 `assemble/translator.py` 直接调用 `translate_guidance`；被 `reviewer._backtrans_compare_system` 调用 `label`。

## 流水线协作总览

按 `Orchestrator` 调用序列：

1. **prepare 阶段**：`Analyzer.analyze(sample)` → `seed_glossary` → `save_analysis`。
2. **预扫阶段**：多线程 `Synopsizer.digest_chapter(src)` → `book_synopsis(digests, style_brief)`。
3. **翻译阶段**（每章每批）：`Translator.translate_batch(...)` → 可选 `Polisher.polish(...)`。
4. **审校阶段**：chunk 维度并发 `Reviewer.review(...)` → 抽样 `BackTranslator.check(...)`。
5. **autofix 阶段**：`Translator.retranslate_with_feedback(...)`。
6. **章末术语抽取**：`GlossaryExtractor.extract_and_store(...)`（见 [06-glossary.md](06-glossary.md)）。
7. **全书一致性 QA**：`ConsistencyChecker.check(store, glossary)`。

## LLM 档位使用约定

| 档位 | Agent / 方法 |
|------|--------------|
| **strong** | `Analyzer.analyze`、`Translator._call_batch` / `retranslate_with_feedback`、`Polisher.polish`、`Orchestrator._translate_titles` |
| **cheap** | `Reviewer.review`、`ConsistencyChecker.check`、`BackTranslator.check`（语义比对步）、`Orchestrator._detect_language_ai` |
| **fast** | `Synopsizer.digest_chapter` / `book_synopsis` / `_synth`、`BackTranslator.backtranslate`、`GlossaryExtractor.extract` |
