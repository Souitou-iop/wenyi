# 03 · 输入解析与切分（ingest）

`ingest` 模块负责把 EPUB / FB2 / TXT / Markdown 解析为统一的 `Document → Chapter → Segment` 结构，并支持超长段切分与翻译批次打包。

## 文件：`ingest/models.py` — 数据契约

定义整个流水线共享的核心数据结构（pydantic v2）。

```python
KIND_TEXT = "text"
KIND_HEADING = "heading"
```

### `Segment`

最小可翻译/可回填单元（一个段落或一个标题）。

| 字段 | 类型 | 说明 |
|------|------|------|
| `index` | `int` | 章内序号 |
| `source` | `str` | 原文 |
| `kind` | `str` | `"text"` 或 `"heading"` |
| `target` | `Optional[str]` | 译文（翻译后填入） |
| `anchor` | `Optional[str]` | EPUB 回填定位标记（`data-tn-id` 占位 id） |
| `cont` | `bool` | 超长段拆分后的续段标记（回填时并回上一段） |
| `meta` | `dict[str, Any]` | 扩展字段（存 `source_digest` 章节梗概等） |

方法：`to_dict()` / `from_dict(d)`。

### `Chapter`

| 字段 | 类型 | 说明 |
|------|------|------|
| `index` | `int` | 全书章序号 |
| `title` | `str` | 章节标题 |
| `segments` | `list[Segment]` | 该章所有段 |
| `href` | `Optional[str]` | EPUB spine item 内部 zip 路径 |
| `template` | `Optional[str]` | EPUB 带占位符的整份 XHTML（回填模板） |
| `meta` | `dict[str, Any]` | `source_digest` / `review_issues` / `backtranslation_issues` |

属性：`text_segments` —— 返回 `source.strip()` 非空的 Segment（真正送翻译的部分）。

### `Document`

| 字段 | 类型 | 说明 |
|------|------|------|
| `title` | `str` | 书名 |
| `source_lang` | `str` | 源语言 |
| `target_lang` | `str` | 目标语言 |
| `fmt` | `str` | `"epub"` / `"text"` / `"fb2"` |
| `source_path` | `str` | 输入文件路径 |
| `chapters` | `list[Chapter]` | 全书章节 |
| `meta` | `dict[str, Any]` | EPUB 的 `opf_path` / `toc_paths` / `toc_entries` |

## 文件：`ingest/epub_reader.py` — EPUB 解析

EPUB 本质是 zip，内含 XHTML + OPF + NCX/NAV。解析流程：

1. **找 OPF**：读 `META-INF/container.xml` 的 `rootfile full-path`（`_find_opf_path`）。
2. **解析 OPF**：`_parse_opf` 返回 `(书名, spine 顺序的 XHTML zip 路径列表, TOC 文件路径列表)`。
3. **建 TOC 标签映射**：`_toc_label_map` 兼容 EPUB 2 (NCX) 与 EPUB 3 (NAV `<nav epub:type="toc">`)，返回 `zip href → 首个 TOC 标签`。
4. **逐章提取**：按 spine 顺序读 XHTML，`_extract_chapter` 用 BeautifulSoup（lxml 后端）解析：
   - `_wrap_direct_body_text` 把 body 直接子节点的散文本/inline 元素包成 `<span data-tn-loose>`。
   - 选出块级元素（`p / h1-h6 / li / blockquote` + 被包裹的 loose 节点），跳过嵌套块。
   - 为每个块打 `data-tn-id="tn{ci}_{idx}"` 占位，产出 `Segment(index, source, kind, anchor)`。
   - 标题取值优先级：TOC 标签 → 首个 heading 文本 → 非内部文件名/书名的 `<title>` → 空标题（`_looks_like_internal_title` 排除"文件名当 title"等情况）。
5. **跳过无正文页**：封面/版权页等无块级元素的 XHTML 被跳过，由 `assemble/writer` 原样拷贝。

### 关键函数

```python
def read_epub(path: str, source_lang: str, target_lang: str) -> Document
```
入口函数，返回 `Document(fmt="epub")`，`meta` 含 `opf_path` / `toc_paths` / `toc_entries`。

```python
def _extract_chapter(html, chapter_index, href, *, book_title, toc_title) -> tuple[str, list[Segment], str]
```
返回 `(title, segments, template_html)`。`template_html` 是带 `data-tn-id` 的整份 XHTML，是回填模板。

### 常量

- `_BLOCK_TAGS = {"p","h1"-"h6","li","blockquote"}`：当作 Segment 的块级元素。
- `_HEADING_TAGS = {"h1"-"h6"}`：判定 `KIND_HEADING`。
- `_INLINE_TAGS`：body 直接子节点中的 inline 元素，需包裹后再抽取。

## 文件：`ingest/fb2_reader.py` — FB2 解析

FB2 (FictionBook) 是 XML 格式。解析流程：

1. 用 `xml.etree.ElementTree` 解析，先正则匹配 XML 声明里的 encoding（FB2 常见 windows-1251），解码失败兜底 utf-8。
2. 从 `<description><title-info><book-title>` 取书名。
3. 只处理第一个无 `name` 属性的 `<body>`（跳过 `body[name="notes"]` 注释部）。
4. `_walk_sections` 递归遍历 `<section>`：叶子节直接成章；含子节者若有自身正文或部标题，先成章保留，再下钻子节，确保"部 → 章"嵌套结构下不丢正文。
5. `_direct_segments` 只取本 `<section>` 的直接内容：`title` → heading；`subtitle` → heading；`p / v / text-author` → text；容器块（`epigraph/cite/poem/stanza`）递归下钻；`empty-line/image` 跳过。

### 关键函数

```python
def read_fb2(path: str, source_lang: str, target_lang: str) -> Document
```

FB2 **不产** `anchor` / `template`（不回填原文件），由 `assemble` 走通用 EPUB 生成路径。

## 文件：`ingest/text_reader.py` — 纯文本/Markdown 解析

支持 `.txt` / `.md` / `.markdown` / `.text`。章节识别优先级：

1. **Markdown ATX 标题**：`^(#{1,3})\s+(.*\S)$`（`_MD_HEADING`）。
2. **日文章节标记行**：`第N章/話/节/節/回/部/巻`、`序章/終章/序幕/終幕/プロローグ/エピローグ/あとがき/まえがき`（`_JA_CHAPTER`）。
3. **整篇作为一章**（兜底）。

段落 = 以空行分隔的文本块（`re.split(r"\n\s*\n", block)`），块内单换行保留。所有 Segment 都没有 `anchor`（纯文本无锚点），由 `assemble` 按"标题 + 段落（空行分隔）"重建。

### 关键函数

```python
def read_text(path: str, source_lang: str, target_lang: str) -> Document
```

## 文件：`ingest/segmenter.py` — 切分与批次打包

是 ingest 模块对外的主入口。

### `load_document`

```python
def load_document(path: str, source_lang: str, target_lang: str,
                  split_segments: int = 0) -> Document
```
按扩展名分发到 `read_epub` / `read_text` / `read_fb2`；`split_segments > 0` 时调用 `split_long_segments` 拆超长段；不支持格式 raise `ValueError`。

### `split_long_segments`

```python
def split_long_segments(chapters: list[Chapter], max_chars: int) -> None
```
就地把各章里超过 `max_chars` 的 Segment 按句切成多段：
- 首段保留 `anchor` 且 `cont=False`。
- 续段 `cont=True`、`anchor=None`、`kind=KIND_TEXT`。
- 拆完重新编号章内 `index`。

`cont` 续段标记被 `assemble/writer` 用来把续段并回同一段落/同一 EPUB 元素，保持结构一一对应。

切句规则（`_SENT_SPLIT`）：在 `。．.!！？!?…\n` 之后拆分。单句本身超长时按空白（空格/Tab/换行）兜底切，找不到空白才硬切。

### `batch_segments` / `chapter_batches`

```python
def batch_segments(segments: list[Segment], max_chars: int) -> list[list[Segment]]
def chapter_batches(chapter: Chapter, max_chars: int) -> list[list[Segment]]
```
按字符预算贪心打包成批次。一个批次整体发给翻译模型，模型须返回等长译文数组以做对齐校验。`chapter_batches` 直接复用 `batch_segments(chapter.text_segments, ...)`，跳过空 Segment。

## 与其他模块的协作

- 被 `pipeline/orchestrator.py` 调用 `load_document` 加载书籍、用 `batch_segments` 切翻译批次、用 `_progress_counts` 计算进度。
- 被 `cli.py:_runstore_for` 调用 `load_document` 推断 `run_dir`（`state_dir/<slug(title)>`）。
- 产出的 `Chapter.template` + `Segment.anchor` 给 `assemble/writer.py` 按 `data-tn-id` 回填译文。
- `Segment.cont` 给 `assemble/writer._merged_paragraphs` 把续段并回。
- 不直接依赖 glossary / agents / llm 模块。
