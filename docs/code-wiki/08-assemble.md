# 08 · 回填组装与后处理（assemble + postprocess）

`assemble` 模块把译文写回原格式（EPUB / 纯文本），并生成 QA 报告。`postprocess` 模块做标点规范化。`assemble/translator.py` 还包含真实 `Translator` 实现（详见 [05-agents.md](05-agents.md)）。

## 模块结构

```
assemble/
├── __init__.py     # 仅文档字符串
├── about.py        # 书末"关于此翻译"说明页
├── report.py       # QA 报告生成
├── translator.py   # 真实 Translator 实现（AlignmentError + 段对齐）
└── writer.py       # 回填核心：EPUB/TXT 生成

postprocess/
├── __init__.py     # 空
└── punct.py        # 标点规范化
```

## 文件：`assemble/writer.py` — 回填核心

### 职责

把译文回填到原格式：
- **纯文本**：按章重建（标题 + 空行分隔段落）。
- **EPUB**：重开原始 zip 逐条目原样拷贝，命中章节 href 的 XHTML 用 `chapter.template` 按 `data-tn-id` 锚点替换译文后写回，非正文资源不动；缺失译文回退原文。
- 支持双语版（`tn-source` 淡背景块）、横排强制（处理竖排源书）、目录译名同步、OPF 元数据语言改写。

### 关键函数

#### 入口

```python
def assemble(store: RunStore, source_path: str, out_path: str | None = None,
             out_format: str = "epub", *, bilingual: bool = False,
             order: str = "target_first", about_page: bool = True) -> str
```
统一入口，根据 `out_format` 和原文格式分派；`about_page=True` 时调用 `append_about_page` 追加说明页。

#### 路径辅助

```python
def _sanitize_filename(name: str, fallback: str = "translated") -> str
def _default_out(source_path: str, out_format: str, title: str | None = None,
                 *, bilingual: bool = False) -> str
    # 在输入文件同级 output/ 目录下生成默认导出路径，后缀 .zh 或 .zh-bi
def bilingual_out_path(out_path: str) -> str
    # 派生双语版路径（stem 追加 -bi）
```

#### 段落合并

```python
def _merged_paragraphs(chapter: Chapter) -> list[tuple[str, str, str]]
    # 把 cont 续段合并回上一段，返回 [(kind, target, source), ...]
```
`Segment.cont=True` 的续段（超长段拆分产物）在回填时并回上一段，保持结构一一对应。

```python
def _bilingual_source(source: str, target: str) -> str
    # 双语原文去重——空白或与译文相同时不输出
```

#### 纯文本回填

```python
def _assemble_text(store, out_path, *, bilingual=False, order="target_first") -> str
```
按章 + 空行分隔段落。续段合并后输出。

#### EPUB 回填

```python
def _assemble_epub(store, source_path, out_path, *,
                   bilingual=False, order="target_first") -> str
```
原文是 EPUB 时：按原模板回填并保留排版/资源。

```python
def _render_chapter_html(chapter, *, bilingual=False, order="target_first") -> str
```
用 BeautifulSoup 渲染单章 XHTML：
- 按 `data-tn-id`（即 `Segment.anchor`）替换元素文本。
- 双语模式下 `p` 用 `insert_before/after` 插入原文，`li/blockquote` 用 append/insert 避免破坏列表结构。

```python
def _build_epub_from_chapters(store, out_path, *,
                              bilingual=False, order="target_first") -> str
```
原文是 fb2/txt 时：用 `ebooklib` 从章节数据生成规范 EPUB3。

#### EPUB 元数据与样式

```python
def _rewrite_opf_metadata(data, *, book_title, lang, force_horizontal) -> bytes
    # 更新 OPF 元数据（书名、语言、竖排改横排方向）
def _epub_looks_vertical(zf) -> bool
    # 粗略检测 EPUB 是否声明竖排
def _rewrite_html_document(data, *, lang, force_horizontal, bilingual=False) -> bytes
    # 注入横排覆盖样式（id=trans-novel-horizontal-override）
    # 和双语原文样式（id=tn-bilingual-style，含暗色模式适配）
def _rewrite_toc(data, title_by_base, *, is_ncx) -> bytes
    # 把 NCX navLabel / EPUB3 nav <a> 标题改为译名
    # EPUB3 仅改 epub:type="toc" 的导航，避免误改 landmarks/page-list
```

译文元数据默认设为简体中文，并将竖排样式转为横排。

## 文件：`assemble/about.py` — 书末说明页

### 职责

生成书末"关于此翻译"说明页，并将其原子地追加进已生成的 EPUB 文件 spine 末尾。

### 关键函数

```python
def about_xhtml(lang: str) -> bytes
    # 返回可独立加入 EPUB spine 的 XHTML 页面字节流
    # 包含文译项目介绍、GitHub 仓库链接和 QQ 群信息
def rootfile_path(container_xml: bytes) -> str | None
    # 从 META-INF/container.xml 解析 OPF rootfile full-path
def unique_about_entry(existing_names: set[str], opf_path: str) -> tuple[str, str]
    # 返回不与原书资源冲突的 (zip 内路径, OPF 相对 href)
    # 必要时追加数字后缀
def append_about_to_opf(data: bytes, href: str) -> bytes
    # 把说明页加入 OPF <manifest> 并作为 <spine> 最后一项 <itemref>
    # item id 自动去重为 trans-novel-about[-N]
def append_about_page(epub_path: str, lang: str) -> bool
    # 对已生成的 EPUB 做原子后处理，使用 tmp + os.replace 写回
    # 保证即使中途失败也不破坏原文件
```

## 文件：`assemble/report.py` — QA 报告

### 职责

QA 报告生成，把术语冲突、审校问题、回译问题、漏译空段集中汇总到一处，供人工裁决。

### 关键函数

```python
def build_report(store: RunStore, glossary: GlossaryStore) -> dict[str, Any]
```

流程：
- 从 `RunStore` 加载 `manifest`，统计总章节数与已完成章节数。
- 遍历已完成章节，收集 `review_issues`、`backtranslation_issues`、`empty_targets`（译文为空的段，附带章节号和原文前 60 字符）。
- 从 `GlossaryStore` 获取开放冲突列表与统计。

返回结构化字典：

```python
{
    "summary": {
        "chapters_done": int,
        "chapters_total": int,
        "terms": int,
        "open_conflicts": int,
        "review_issues": int,
        "backtranslation_issues": int,
        # ...
    },
    "open_conflicts": [...],
    "review_issues": [...],
    "backtranslation_issues": [...],
    "empty_targets": [...]
}
```

`Orchestrator.run_steps` 在 report 阶段调用后还会附加 `report["consistency_issues"] = qa_issues`。

## 文件：`postprocess/punct.py` — 标点规范化

### 职责

译文标点规范化，统一为简体中文大陆通用全角标点。作为提示词要求之后的**确定性兜底**。

### 关键常量

```python
_CJK  # CJK 汉字、假名、全角符号字符集
_HALF_TO_FULL  # 半角标点到全角的映射字典
```

### 主要函数

```python
def normalize_zh(text: str) -> str
    # 主入口，依次执行下面三步，最后清理全角标点后的多余空格
```

#### 内部步骤

```python
def _convert_quotes(text: str) -> str
```
- 日式引号 `「」→""`、`『』→''`。
- 英式直双引号按出现次序交替配对。
- 直单引号在字母间保留为 `'`（撇号），其余成对交替配对。

```python
def _convert_ellipsis_dash(text: str) -> str
```
- 连续点号 `。{3,}` / `・{2,}` / `\.{3,}` 归一为 `……`。
- `-{2,}` / `—+` 归一为 `——`，多余 `——————` 合并为 `——`。

```python
def _convert_halfwidth(text: str) -> str
```
- 半角 `,.!?:;` 紧邻 CJK 字符时转全角。
- **避免误伤**英文/数字内部如 `9.11`、`Mr. Smith`。

### 调用位置

- `Orchestrator._process_batch`：每批翻译后若 `punctuation_normalize=True` 则对每段调用。
- `Orchestrator._autofix_severe`：定向重译采纳前调用。
- `assemble/writer.py`：回填时不调用（已在翻译阶段做过）。

## 与其他模块的协作

- `assemble/writer.py` 依赖 `ingest/models.py` 的 `Segment.anchor` / `Chapter.template` / `Segment.cont` 做回填定位与续段合并。
- `assemble/translator.py` 依赖 `agents/base.py:Agent`、`agents/prompts.py`、`agents/langprofile.py`、`glossary/store.py:GlossaryTerm`（详见 [05-agents.md](05-agents.md)）。
- `assemble/report.py` 依赖 `pipeline/runstore.py:RunStore` 与 `glossary/store.py:GlossaryStore`。
- `postprocess/punct.py` 是纯函数，无外部依赖，被 `pipeline/orchestrator.py` 调用。
- `assemble` 被 `Orchestrator.run_steps` 在 assemble 阶段调用，也被 Web UI 的 `POST /api/tasks/{id}/exports` 重新导出时调用。
