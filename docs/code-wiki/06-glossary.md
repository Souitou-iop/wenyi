# 06 · 术语库与翻译记忆（glossary）

`glossary` 模块负责专有名词对照表 + 翻译记忆库，覆盖术语抽取、入库冲突记录、人工裁决、术语注入翻译 prompt、TM 命中复用等能力。

## 模块结构

```
glossary/
├── __init__.py     # 仅导出 GlossaryStore, GlossaryTerm
├── store.py        # SQLite 持久化（三张表）
├── extractor.py    # GlossaryExtractor（继承 Agent，术语抽取）
└── resolver.py     # 人工裁决辅助（CLI 用）
```

注意 `extractor.py` 与 `resolver.py` 未在 `__init__` 导出，由调用方按需 import。

## 文件：`glossary/store.py` — SQLite 持久化

### 术语类型常量

```python
TYPE_PERSON = "人物"
TYPE_PLACE = "地名"
TYPE_ORG = "组织"
TYPE_TERM = "术语"
TYPE_SKILL = "招式"
TYPE_APPELLATION = "称谓"
TYPE_HONORIFIC = "敬称"
TYPE_SPEECH = "口癖"
TYPE_FIXED_EXPR = "固定表达"
TYPE_ONOMATOPOEIA = "拟声词"

_SOURCE_ONLY_TYPES = {TYPE_APPELLATION, TYPE_HONORIFIC, TYPE_SPEECH, TYPE_FIXED_EXPR}
# 这些类型在 terms_in 里只按 source 命中，不算 alias（避免派生写法污染普通称呼处）
```

### `GlossaryTerm` 数据类

```python
@dataclass
class GlossaryTerm:
    source: str
    target: str
    reading: str = ""                 # 假名读音（日语用）
    type: str = TYPE_TERM
    gender: str = ""                  # male/female/unknown
    aliases: list[str] = field(default_factory=list)
    first_chapter: Optional[int] = None
    note: str = ""
    status: str = "ok"                # ok | conflict

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "GlossaryTerm"
        # aliases 用 json.loads 反序列化
```

### SQLite 表结构（`_SCHEMA`）

三张表：

**`glossary`**（source 为主键）：
```
source, target, reading, type, gender, aliases(JSON),
first_chapter, note, status, updated_at
```

**`term_conflicts`**（自增 id）：
```
id, source, existing_target, proposed_target, chapter,
note, resolved(默认 0), created_at
```

**`translation_memory`**（`source_hash` 为主键）：
```
source_hash, source_text, target_text, chapter, updated_at
```

### `GlossaryStore` 类

```python
class GlossaryStore:
    def __init__(self, db_path: str)
        # 打开 SQLite，row_factory=Row, busy_timeout=5000, journal_mode=WAL
        # 执行 _SCHEMA，调用 _migrate_legacy_glossary_schema
    def close(self) -> None
```

WAL 模式 + `busy_timeout=5000` 兼顾 Web 编辑与翻译 worker 并发写。

#### `_migrate_legacy_glossary_schema`

从旧库移除 `confidence/locked` 字段，保留全部术语数据：rename 到 `glossary_legacy_priority` → 建新表 → INSERT 回填 → DROP 临时表。

#### 术语 CRUD

```python
def get_term(self, source: str) -> Optional[GlossaryTerm]
def upsert_term(self, term: GlossaryTerm, chapter: Optional[int] = None) -> str
    # 返回 'inserted' | 'unchanged' | 'conflict'
def delete_term(self, source: str) -> bool
def resolve_term(self, source: str, target: str) -> bool
def all_terms(self) -> list[GlossaryTerm]
```

##### `upsert_term` 核心冲突逻辑

整个流程在 `BEGIN IMMEDIATE` 事务中：

- 同 source **不存在** → INSERT，返回 `inserted`。
- 同 source **同 target** → 合并 aliases/补全 reading/gender/note，返回 `unchanged`。
- 同 source **不同 target** → 保留当前译法，调用 `_log_conflict` 写入 `term_conflicts`，并把 `status` 置为 `conflict`，返回 `conflict`。

不同译法由 `upsert_term` 自动记录到冲突表，等待人工裁决。

#### 术语命中查询

```python
@staticmethod
def terms_in(terms: list[GlossaryTerm], text: str) -> list[GlossaryTerm]
def terms_in_text(self, text: str) -> list[GlossaryTerm]
```

- `terms_in`：从术语列表里筛出 source 或任一 alias 在文本中出现的项；`_SOURCE_ONLY_TYPES` 只按 source 命中。**接受预取快照避免逐批重复查库**（章内术语表不变）。
- `terms_in_text`：实例方法，先 `all_terms()` 再 `terms_in`。

#### 冲突管理

```python
def mark_conflicts_resolved(self, source: str) -> None   # 该 source 的所有 conflict 行 resolved=1
def open_conflicts(self) -> list[dict[str, Any]]         # 列出 resolved=0 的冲突
```

#### 翻译记忆库

```python
def add_tm(self, source_text: str, target_text: str, chapter: Optional[int] = None) -> None
    # ON CONFLICT(source_hash) DO UPDATE 覆写
def tm_lookup(self, source_text: str) -> Optional[str]
```

模块级辅助：`_hash(text)` = sha256 hex，用于 TM 主键。

> 注意：翻译记忆库**仅作记录/参考，不用于跨位置复用译文**（避免丢失语境信息）。`Orchestrator._translate_chapter` 章末把每段 `(source, target)` 写入 TM，但翻译时不读 TM。

#### 统计

```python
def stats(self) -> dict[str, int]   # {terms, open_conflicts, tm_entries}
```

## 文件：`glossary/extractor.py` — GlossaryExtractor

```python
class GlossaryExtractor(Agent):
    def extract(self, source_text: str, target_text: str,
                existing: list[GlossaryTerm]) -> list[GlossaryTerm]
    def extract_and_store(self, store: GlossaryStore, source_text: str,
                          target_text: str, chapter: int) -> dict[str, int]
```

### 流水线位置

术语抽取 Agent（**fast 档**）。每翻完一章，从"原文 + 译文"里抽取应进表的专有名词，依据实际译法入库；不同译法由 `GlossaryStore.upsert_term` 记录到冲突表，等待人工裁决。

### 方法说明

- **`extract(source_text, target_text, existing)`**：用 `prompts.render("glossary_extractor_system", ...)` 和 `prompts.render("glossary_extractor_user", glossary=prompts.render_glossary(existing), source=..., target=...)` 渲染 prompt；调用基类 `Agent._ask_json(system, user, tier="fast", key="terms", default=[])` 拿 JSON list；用 `dict_items` 过滤出 dict 元素；逐项构造 `GlossaryTerm`（source/target/reading/type/gender/aliases/note），缺 source 或 target 跳过；`gender` 为"未知"/None 时归一为空串。
- **`extract_and_store(store, source_text, target_text, chapter)`**：先取 `store.all_terms()` 作为 existing，调 `extract` 得到候选列表；逐项设 `first_chapter = chapter`，调 `store.upsert_term(t, chapter=chapter)`，按返回值（`inserted/conflict/unchanged`）累加 summary 并返回。

### 调用时机

被 `Orchestrator` 在三个位置调用：
1. **每批译完/续跑跳过后**：`_extract_batch_glossary` → `extract_and_store`（即时抽取，供同章后续批次使用）。
2. **章末全章兜底抽取**：`extractor.extract_and_store(glossary, src_text, tgt_text, ci)`（捕捉跨段才能确认的称呼/口癖）。
3. **Analyzer.seed_glossary**：前期分析时把角色/术语种入（不经过 extractor，直接 upsert）。

## 文件：`glossary/resolver.py` — 人工裁决辅助

```python
def resolve(store: GlossaryStore, source: str, target: str) -> bool
def pending_review(store: GlossaryStore) -> dict
```

### 职责

术语冲突的人工裁决辅助（供 CLI 使用）。自动冲突判定在 `GlossaryStore.upsert_term` 内完成；本模块提供"人工拍板"封装：确定某词的最终译法，并把相关冲突标记为已解决。

### 方法说明

- **`resolve(store, source, target)`**：先调 `store.resolve_term(source, target)` 把最终译法写入并恢复 `status='ok'`，成功则调 `store.mark_conflicts_resolved(source)` 把该 source 的所有 conflict 行置 `resolved=1`；返回术语是否存在。
- **`pending_review(store)`**：返回 `{"conflicts": store.open_conflicts()}`，即所有未解决冲突列表。

### 协作

被 CLI 的 `tools glossary ... resolve` 子命令调用（见 [09-cli.md](09-cli.md)），也被 Web UI 的 `POST /api/tasks/{id}/glossary/conflicts/{conflict_id}/resolve` 间接调用（Web UI 直接调 `GlossaryStore` 方法，不经 resolver 模块）。

## 与其他模块的协作

- 被 `glossary/extractor.py` 调用 `all_terms` / `upsert_term`。
- 被 `glossary/resolver.py` 调用 `resolve_term` / `mark_conflicts_resolved` / `open_conflicts`。
- 被 `agents/translator.py`（assemble/translator.py）等通过 `terms_in_text` 注入翻译 prompt（实际通过 `Orchestrator._chapter_term_snapshot` 取快照传入）。
- 被 `Orchestrator._translate_chapter` 章末调 `add_tm` 写翻译记忆。
- 被 CLI/Web 通过 `stats` / `delete_term` / `resolve_term` 暴露给前端编辑。
- WAL + busy_timeout 设计兼顾 Web 编辑与翻译 worker 并发写。
