import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  api,
  type Analysis,
  type ChapterDetail,
  type ChapterSummary,
  type GlossaryConflict,
  type GlossaryTerm,
  type Task,
  type TaskEvent,
  type TaskExport,
  type Usage,
  type UsageCounts,
} from "./api";

type Tab = "overview" | "glossary" | "analysis" | "review" | "exports" | "events" | "usage";

const tabs: { id: Tab; label: string }[] = [
  { id: "overview", label: "概览" },
  { id: "glossary", label: "术语" },
  { id: "analysis", label: "风格概要" },
  { id: "review", label: "审校" },
  { id: "exports", label: "导出" },
  { id: "events", label: "事件" },
  { id: "usage", label: "用量" },
];

const number = new Intl.NumberFormat("zh-CN");
const errorMessage = (reason: unknown, fallback: string) =>
  reason instanceof Error ? reason.message : fallback;

export default function AdvancedWorkspace({
  task,
  overview,
  onError,
}: {
  task: Task;
  overview: ReactNode;
  onError: (message: string) => void;
}) {
  const [tab, setTab] = useState<Tab>("overview");

  return (
    <section className="advanced-workspace">
      <nav className="advanced-tabs" aria-label="任务工作区">
        {tabs.map((item) => (
          <button
            key={item.id}
            type="button"
            className={tab === item.id ? "active" : ""}
            aria-current={tab === item.id ? "page" : undefined}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>
      <div className="advanced-panel">
        {tab === "overview" ? overview : null}
        {tab === "glossary" ? <GlossaryPanel task={task} onError={onError} /> : null}
        {tab === "analysis" ? <AnalysisPanel task={task} onError={onError} /> : null}
        {tab === "review" ? <ReviewPanel task={task} onError={onError} /> : null}
        {tab === "exports" ? <ExportsPanel task={task} onError={onError} /> : null}
        {tab === "events" ? <EventsPanel task={task} onError={onError} /> : null}
        {tab === "usage" ? <UsagePanel task={task} onError={onError} /> : null}
      </div>
    </section>
  );
}

function PanelState({
  loading,
  ready,
  empty,
  children,
}: {
  loading: boolean;
  ready: boolean;
  empty?: string;
  children: ReactNode;
}) {
  if (loading) return <p className="advanced-empty">正在载入…</p>;
  if (!ready) return <p className="advanced-empty">翻译工作区正在准备，高级数据生成后会显示在这里。</p>;
  if (empty) return <p className="advanced-empty">{empty}</p>;
  return children;
}

function GlossaryPanel({ task, onError }: { task: Task; onError: (message: string) => void }) {
  const [terms, setTerms] = useState<GlossaryTerm[]>([]);
  const [conflicts, setConflicts] = useState<GlossaryConflict[]>([]);
  const [ready, setReady] = useState(true);
  const [editable, setEditable] = useState(false);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState("");
  const [query, setQuery] = useState("");
  const [type, setType] = useState("");
  const [source, setSource] = useState("");
  const [target, setTarget] = useState("");

  const load = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true);
    try {
      const [termData, conflictData] = await Promise.all([
        api.glossaryTerms(task.id, query, type),
        api.glossaryConflicts(task.id),
      ]);
      setTerms(termData.terms);
      setConflicts(conflictData.conflicts);
      setReady(termData.workspace_ready);
      setEditable(termData.editable);
    } catch (reason) {
      onError(errorMessage(reason, "无法载入术语"));
    } finally {
      if (showLoading) setLoading(false);
    }
  }, [onError, query, task.id, type]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 180);
    return () => window.clearTimeout(timer);
  }, [load, task.phase_code, task.status, task.workspace_ready]);

  useEffect(() => {
    if (task.status !== "running" || ready) return;
    const timer = window.setInterval(() => void load(false), 5000);
    return () => window.clearInterval(timer);
  }, [load, ready, task.status]);

  const mutate = async (key: string, action: () => Promise<unknown>) => {
    if (pending) return;
    setPending(key);
    try {
      await action();
      await load();
    } catch (reason) {
      onError(errorMessage(reason, "无法更新术语"));
    } finally {
      setPending("");
    }
  };

  const add = () => {
    const nextSource = source.trim();
    const nextTarget = target.trim();
    if (!nextSource || !nextTarget) return;
    void mutate("add", async () => {
      await api.addGlossaryTerm(task.id, { source: nextSource, target: nextTarget });
      setSource("");
      setTarget("");
    });
  };

  return (
    <PanelState loading={loading} ready={ready}>
      <div className="advanced-heading">
        <div><h2>术语库</h2><p>运行中修改只影响后续章节，已完成章节不会自动重译。</p></div>
      </div>
      <div className="advanced-toolbar">
        <input aria-label="搜索术语" placeholder="搜索原文或译文" value={query} onChange={(event) => setQuery(event.target.value)} />
        <select aria-label="术语类型" value={type} onChange={(event) => setType(event.target.value)}>
          <option value="">全部类型</option>
          <option value="person">人物</option>
          <option value="place">地点</option>
          <option value="organization">组织</option>
          <option value="term">专有词</option>
        </select>
      </div>
      {editable ? (
        <div className="term-create">
          <input aria-label="术语原文" placeholder="原文" value={source} onChange={(event) => setSource(event.target.value)} />
          <input aria-label="术语译文" placeholder="译文" value={target} onChange={(event) => setTarget(event.target.value)} />
          <button className="button quiet" disabled={pending === "add" || !source.trim() || !target.trim()} onClick={add}>
            {pending === "add" ? "添加中…" : "添加术语"}
          </button>
        </div>
      ) : null}
      {conflicts.length ? (
        <section className="conflict-list">
          <h3>待处理冲突</h3>
          {conflicts.map((conflict) => (
            <article key={conflict.id} className="conflict-card">
              <div><strong>{conflict.source}</strong><p>{conflict.reason}</p></div>
              <div className="conflict-choices">
                <button aria-label={`为「${conflict.source}」保留当前译法`} disabled={Boolean(pending)} onClick={() => void mutate(`conflict-${conflict.id}`, () => api.resolveGlossaryConflict(task.id, conflict.id, "current"))}>
                  保留「{conflict.current}」
                </button>
                <button aria-label={`为「${conflict.source}」采用建议译法`} disabled={Boolean(pending)} onClick={() => void mutate(`conflict-${conflict.id}`, () => api.resolveGlossaryConflict(task.id, conflict.id, "proposed"))}>
                  采用「{conflict.proposed}」
                </button>
              </div>
            </article>
          ))}
        </section>
      ) : null}
      {terms.length ? (
        <div className="term-table-wrap">
          <table className="advanced-table">
            <thead><tr><th>原文 / 读音</th><th>译文</th><th>类型</th><th>置信度</th><th><span className="sr-only">操作</span></th></tr></thead>
            <tbody>
              {terms.map((term) => (
                <tr key={term.source}>
                  <td><strong>{term.source}</strong>{term.reading ? <small>{term.reading}</small> : null}</td>
                  <td>{term.target}</td>
                  <td>{term.type || "—"}</td>
                  <td>{term.confidence == null ? "—" : { low: "低", medium: "中", high: "高" }[term.confidence]}</td>
                  <td className="table-actions">
                    <button aria-label={`${term.locked ? "解锁" : "锁定"}术语「${term.source}」`} disabled={!editable || Boolean(pending)} onClick={() => void mutate(`lock-${term.source}`, () => api.setGlossaryLock(task.id, term.source, !term.locked))}>
                      {term.locked ? "解锁" : "锁定"}
                    </button>
                    <button
                      className="danger-link"
                      aria-label={`删除术语「${term.source}」`}
                      disabled={!editable || Boolean(pending)}
                      onClick={() => {
                        if (window.confirm(`确定删除术语「${term.source}」吗？`)) {
                          void mutate(`delete-${term.source}`, () => api.removeGlossaryTerm(task.id, term.source));
                        }
                      }}
                    >
                      删除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="advanced-empty compact">没有符合条件的术语。</p>}
    </PanelState>
  );
}

function AnalysisPanel({ task, onError }: { task: Task; onError: (message: string) => void }) {
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [ready, setReady] = useState(true);
  const [editable, setEditable] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [styleGuide, setStyleGuide] = useState("");
  const [synopsis, setSynopsis] = useState("");
  const serverStyleGuide = useRef("");
  const serverSynopsis = useRef("");
  const styleGuideDirty = useRef(false);
  const synopsisDirty = useRef(false);
  const savingRef = useRef(false);

  const load = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true);
    try {
      const data = await api.analysis(task.id);
      setReady(data.workspace_ready);
      setEditable(data.editable);
      setAnalysis(data.analysis);
      const nextStyleGuide = data.analysis?.style_guide || "";
      const nextSynopsis = data.analysis?.book_synopsis || "";
      serverStyleGuide.current = nextStyleGuide;
      serverSynopsis.current = nextSynopsis;
      if (!savingRef.current && !styleGuideDirty.current) setStyleGuide(nextStyleGuide);
      if (!savingRef.current && !synopsisDirty.current) setSynopsis(nextSynopsis);
    } catch (reason) {
      onError(errorMessage(reason, "无法载入风格概要"));
    } finally {
      if (showLoading) setLoading(false);
    }
  }, [onError, task.id]);

  useEffect(() => {
    void load();
  }, [load, task.phase_code, task.status, task.workspace_ready]);

  useEffect(() => {
    if (task.status !== "running" || (ready && analysis)) return;
    const timer = window.setInterval(() => void load(false), 5000);
    return () => window.clearInterval(timer);
  }, [analysis, load, ready, task.status]);

  const save = async () => {
    setSaving(true);
    savingRef.current = true;
    try {
      const data = await api.saveAnalysis(task.id, { style_guide: styleGuide, book_synopsis: synopsis });
      setAnalysis(data.analysis);
      serverStyleGuide.current = data.analysis?.style_guide ?? styleGuide;
      serverSynopsis.current = data.analysis?.book_synopsis ?? synopsis;
      styleGuideDirty.current = false;
      synopsisDirty.current = false;
      setStyleGuide(serverStyleGuide.current);
      setSynopsis(serverSynopsis.current);
    } catch (reason) {
      onError(errorMessage(reason, "无法保存风格概要"));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  };

  const facts = analysis ? [
    ["体裁", analysis.genre],
    ["语调", analysis.tone],
    ["叙事", analysis.narration],
    ["节奏", analysis.pacing],
    ["对话风格", analysis.dialogue_style],
    ["修辞", analysis.rhetoric],
  ] : [];

  return (
    <PanelState loading={loading} ready={ready} empty={!analysis ? "尚未生成风格概要。" : undefined}>
      <div className="advanced-heading"><div><h2>风格概要</h2><p>预扫完成后可编辑；运行中修改只影响后续章节。</p></div></div>
      <dl className="analysis-facts">
        {facts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || "—"}</dd></div>)}
      </dl>
      {analysis?.characters?.length ? (
        <details className="advanced-details"><summary>角色信息 · {analysis.characters.length}</summary><pre>{JSON.stringify(analysis.characters, null, 2)}</pre></details>
      ) : null}
      {analysis?.chapter_summaries?.length ? (
        <details className="advanced-details"><summary>章节摘要 · {analysis.chapter_summaries.length}</summary><pre>{JSON.stringify(analysis.chapter_summaries, null, 2)}</pre></details>
      ) : null}
      <label className="advanced-field"><span>风格指南</span><textarea value={styleGuide} disabled={!editable || saving} onChange={(event) => {
        setStyleGuide(event.target.value);
        styleGuideDirty.current = event.target.value !== serverStyleGuide.current;
      }} /></label>
      <label className="advanced-field"><span>全书概要</span><textarea value={synopsis} disabled={!editable || saving} onChange={(event) => {
        setSynopsis(event.target.value);
        synopsisDirty.current = event.target.value !== serverSynopsis.current;
      }} /></label>
      <button className="button primary" disabled={!editable || saving} onClick={() => void save()}>{saving ? "保存中…" : "保存概要"}</button>
    </PanelState>
  );
}

function ReviewPanel({ task, onError }: { task: Task; onError: (message: string) => void }) {
  const [chapters, setChapters] = useState<ChapterSummary[]>([]);
  const [chapter, setChapter] = useState<ChapterDetail | null>(null);
  const [editable, setEditable] = useState(false);
  const [ready, setReady] = useState(true);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState("");
  const [savedSegment, setSavedSegment] = useState<number | null>(null);
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const chapterRequest = useRef(0);
  const hasLoadedChapter = useRef(false);

  const loadChapter = useCallback(async (index: number) => {
    const request = ++chapterRequest.current;
    if (!hasLoadedChapter.current) setLoading(true);
    try {
      const data = await api.chapter(task.id, index);
      if (request !== chapterRequest.current) return;
      setReady(data.workspace_ready);
      setEditable(data.editable);
      setChapter(data.chapter);
      hasLoadedChapter.current = true;
      setSavedSegment(null);
      setDrafts(Object.fromEntries(data.chapter.segments.map((segment) => [segment.index, segment.target])));
    } catch (reason) {
      if (request === chapterRequest.current) {
        onError(errorMessage(reason, "无法载入章节"));
      }
    } finally {
      if (request === chapterRequest.current) setLoading(false);
    }
  }, [onError, task.id]);

  useEffect(() => {
    setLoading(true);
    void api.chapters(task.id).then((data) => {
      const completed = data.chapters.filter((item) => item.status === "done");
      setChapters(completed);
      setReady(data.workspace_ready);
      setEditable(data.editable);
      if (completed[0]) return loadChapter(completed[0].index);
    }).catch((reason) => onError(errorMessage(reason, "无法载入章节")))
      .finally(() => setLoading(false));
  }, [loadChapter, onError, task.id]);

  const currentIndex = chapters.findIndex((item) => item.index === chapter?.index);
  const dirty = Boolean(chapter?.segments.some((segment) => drafts[segment.index] !== segment.target));
  const navigateChapter = (index: number) => {
    if (index === chapter?.index) return;
    if (dirty && !window.confirm("当前章节有尚未保存的修改，确定放弃并切换章节吗？")) return;
    void loadChapter(index);
  };
  const saveSegment = async (segment: number) => {
    if (!chapter || pending) return;
    setPending(`segment-${segment}`);
    try {
      await api.saveSegment(task.id, chapter.index, segment, drafts[segment] ?? "");
      setSavedSegment(segment);
      setChapter((current) => current ? {
        ...current,
        segments: current.segments.map((item) => item.index === segment ? { ...item, target: drafts[segment] ?? "" } : item),
      } : current);
    } catch (reason) {
      onError(errorMessage(reason, "无法保存译文"));
    } finally {
      setPending("");
    }
  };

  const complete = async () => {
    if (!chapter || pending) return;
    setPending("review");
    try {
      await api.completeReview(task.id, chapter.index);
      setChapter({ ...chapter, review_complete: true });
      setChapters((current) => current.map((item) => item.index === chapter.index ? { ...item, review_complete: true } : item));
    } catch (reason) {
      onError(errorMessage(reason, "无法更新审校状态"));
    } finally {
      setPending("");
    }
  };

  return (
    <PanelState loading={loading} ready={ready} empty={!chapters.length ? "暂无已完成章节可供审校。" : undefined}>
      <div className="advanced-heading review-heading">
        <div><h2>{chapter?.title_translated || chapter?.title || "逐章审校"}</h2><p>修改译文后需要重新导出产物。</p></div>
        <div className="chapter-navigation">
          <button disabled={currentIndex <= 0 || loading} onClick={() => navigateChapter(chapters[currentIndex - 1].index)}>上一章</button>
          <select aria-label="审校章节" value={chapter?.index ?? ""} onChange={(event) => navigateChapter(Number(event.target.value))}>
            {chapters.map((item) => <option key={item.index} value={item.index}>{item.title_translated || item.title}</option>)}
          </select>
          <button disabled={currentIndex < 0 || currentIndex >= chapters.length - 1 || loading} onClick={() => navigateChapter(chapters[currentIndex + 1].index)}>下一章</button>
        </div>
      </div>
      {chapter ? (
        <>
          {(chapter.review_issues.length || chapter.backtranslation_issues.length) ? (
            <details className="advanced-details review-issues">
              <summary>审校建议 · {chapter.review_issues.length + chapter.backtranslation_issues.length}</summary>
              <pre>{JSON.stringify([...chapter.review_issues, ...chapter.backtranslation_issues], null, 2)}</pre>
            </details>
          ) : null}
          <div className="segment-list">
            {chapter.segments.map((segment) => {
              const changed = drafts[segment.index] !== segment.target;
              return (
                <article className="segment-card" key={segment.index}>
                  <div className="segment-source"><span>原文</span><p>{segment.source}</p></div>
                  <label><span>译文</span><textarea disabled={!editable || Boolean(pending)} value={drafts[segment.index] ?? ""} onChange={(event) => setDrafts((current) => ({ ...current, [segment.index]: event.target.value }))} /></label>
                  <button className="button quiet" disabled={!editable || !changed || Boolean(pending)} onClick={() => void saveSegment(segment.index)}>
                    {pending === `segment-${segment.index}` ? "保存中…" : "保存本段"}
                  </button>
                  {savedSegment === segment.index && !changed ? <small className="segment-saved">本段已保存，需要重新导出。</small> : null}
                </article>
              );
            })}
          </div>
          <button className="button primary" disabled={!editable || chapter.review_complete || Boolean(pending)} onClick={() => void complete()}>
            {chapter.review_complete ? "已完成人工审校" : pending === "review" ? "标记中…" : "标记本章审校完成"}
          </button>
        </>
      ) : null}
    </PanelState>
  );
}

function ExportsPanel({ task, onError }: { task: Task; onError: (message: string) => void }) {
  const [items, setItems] = useState<TaskExport[]>([]);
  const [ready, setReady] = useState(true);
  const [stale, setStale] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [format, setFormat] = useState<"epub" | "txt">("epub");
  const [bilingual, setBilingual] = useState(false);
  const [order, setOrder] = useState<"source_first" | "target_first">("target_first");
  const [about, setAbout] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.exports(task.id);
      setItems(data.exports);
      setReady(data.workspace_ready);
      setStale(data.outputs_stale);
    } catch (reason) {
      onError(errorMessage(reason, "无法载入导出记录"));
    } finally {
      setLoading(false);
    }
  }, [onError, task.id]);

  useEffect(() => void load(), [load]);

  const create = async () => {
    setSaving(true);
    try {
      await api.createExport(task.id, {
        format,
        mono: !bilingual,
        bilingual,
        bilingual_order: order,
        about_page: about,
      });
      await load();
    } catch (reason) {
      onError(errorMessage(reason, "无法创建导出"));
    } finally {
      setSaving(false);
    }
  };

  const canExport = task.status === "completed"
    || (task.status !== "running" && task.completed >= task.total && task.total > 0);

  return (
    <PanelState loading={loading} ready={ready}>
      <div className="advanced-heading"><div><h2>重新导出</h2><p>{stale ? "译文已修改，现有产物需要重新导出。" : "创建不同格式的独立下载产物。"}</p></div></div>
      <div className="export-options">
        <label><span>格式</span><select value={format} onChange={(event) => setFormat(event.target.value as "epub" | "txt")}><option value="epub">EPUB</option><option value="txt">TXT</option></select></label>
        <label><span>内容</span><select value={bilingual ? "bilingual" : "mono"} onChange={(event) => setBilingual(event.target.value === "bilingual")}><option value="mono">仅译文</option><option value="bilingual">双语</option></select></label>
        <label><span>双语顺序</span><select value={order} disabled={!bilingual} onChange={(event) => setOrder(event.target.value as "source_first" | "target_first")}><option value="target_first">译文在前</option><option value="source_first">原文在前</option></select></label>
        <label className="check-option"><input type="checkbox" checked={about} onChange={(event) => setAbout(event.target.checked)} />加入翻译说明页</label>
        <button className="button primary" disabled={!canExport || saving} onClick={() => void create()}>{saving ? "导出中…" : "创建导出"}</button>
      </div>
      {!canExport ? <p className="advanced-note">全部章节完成且任务停止后才能重新导出。</p> : null}
      <div className="export-list">
        {items.map((item) => (
          <article key={item.id}>
            <div><strong>{item.filename || `${item.format.toUpperCase()} 导出`}</strong><small>{item.historical ? "历史产物" : new Date(item.created_at).toLocaleString("zh-CN")}</small></div>
            <span className={`status-pill ${item.status}`}>{item.status === "completed" ? "已完成" : item.status === "failed" ? "失败" : "处理中"}</span>
            {item.status === "completed" && item.download_url ? <a className="button quiet" href={item.download_url}>下载</a> : null}
            {item.error ? <p>{item.error}</p> : null}
          </article>
        ))}
        {!items.length ? <p className="advanced-empty compact">尚无导出记录。</p> : null}
      </div>
    </PanelState>
  );
}

function EventsPanel({ task, onError }: { task: Task; onError: (message: string) => void }) {
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [types, setTypes] = useState<string[]>([]);
  const [type, setType] = useState("");
  const [ready, setReady] = useState(true);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const data = await api.taskEvents(task.id, type);
      setEvents(data.events);
      setTypes(data.types);
      setReady(data.workspace_ready);
    } catch (reason) {
      onError(errorMessage(reason, "无法载入事件"));
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [onError, task.id, type]);

  useEffect(() => {
    void load();
    if (task.status !== "running") return;
    const timer = window.setInterval(() => void load(true), 5000);
    return () => window.clearInterval(timer);
  }, [load, task.status]);

  return (
    <PanelState loading={loading} ready={ready} empty={!events.length ? "尚无运行事件。" : undefined}>
      <div className="advanced-heading">
        <div><h2>运行事件</h2><p>最多显示最近 200 条。</p></div>
        <div className="event-actions"><select aria-label="事件类型" value={type} onChange={(event) => setType(event.target.value)}><option value="">全部阶段</option>{types.map((item) => <option key={item} value={item}>{item}</option>)}</select><button className="button quiet" onClick={() => void load()}>刷新</button></div>
      </div>
      <ol className="event-list">
        {events.map((event, index) => (
          <li key={`${event.timestamp ?? event.ts ?? ""}-${index}`}>
            <time>{event.timestamp || event.ts ? new Date((event.timestamp ?? event.ts)!).toLocaleTimeString("zh-CN") : "—"}</time>
            <strong>{String(event.phase ?? event.phase_code ?? event.type ?? "事件")}</strong>
            <span>{String(event.message ?? safeEventSummary(event))}</span>
          </li>
        ))}
      </ol>
    </PanelState>
  );
}

function safeEventSummary(event: TaskEvent) {
  const ignored = new Set(["type", "phase", "phase_code", "message", "timestamp", "ts", "api_key", "config_path", "run_dir", "state_dir"]);
  return Object.entries(event)
    .filter(([key, value]) => !ignored.has(key) && ["string", "number", "boolean"].includes(typeof value))
    .slice(0, 3)
    .map(([key, value]) => `${key}: ${String(value)}`)
    .join(" · ") || "状态已更新";
}

function UsagePanel({ task, onError }: { task: Task; onError: (message: string) => void }) {
  const [usage, setUsage] = useState<Usage | null>(null);
  const [hasUsage, setHasUsage] = useState(false);
  const [cacheAvailable, setCacheAvailable] = useState(false);
  const [ready, setReady] = useState(true);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true);
    try {
      const data = await api.usage(task.id);
      setUsage(data.usage);
      setHasUsage(data.has_usage);
      setCacheAvailable(data.cache_available);
      setReady(data.workspace_ready);
    } catch (reason) {
      onError(errorMessage(reason, "无法载入 Token 用量"));
    } finally {
      if (showLoading) setLoading(false);
    }
  }, [onError, task.id]);

  useEffect(() => {
    void load();
  }, [load, task.phase_code, task.status, task.workspace_ready]);

  useEffect(() => {
    if (task.status !== "running") return;
    const timer = window.setInterval(() => void load(false), 5000);
    return () => window.clearInterval(timer);
  }, [load, task.status]);

  const cacheRate = useMemo(() => {
    const hits = usage?.totals.cache_hits;
    const misses = usage?.totals.cache_misses;
    return hits == null || misses == null || hits + misses === 0 ? null : hits / (hits + misses);
  }, [usage]);

  return (
    <PanelState loading={loading} ready={ready} empty={!hasUsage ? "尚无 Token 用量记录。" : undefined}>
      <div className="advanced-heading"><div><h2>Token 用量</h2><p>暂停继续会持续累计，重新翻译会从零计数。</p></div></div>
      {hasUsage && usage ? (
        <>
          <div className="usage-cards">
            <Metric label="调用次数" value={usage.totals.calls} />
            <Metric label="输入 Token" value={usage.totals.input_tokens} />
            <Metric label="输出 Token" value={usage.totals.output_tokens} />
            <Metric label="总 Token" value={usage.totals.total_tokens} accent />
            <Metric label="缓存命中率" value={cacheAvailable && cacheRate != null ? `${Math.round(cacheRate * 100)}%` : "无缓存数据"} />
          </div>
          <UsageBreakdown title="按模型档位" values={usage.by_tier} />
          <UsageBreakdown title="按流程阶段" values={usage.by_stage} />
        </>
      ) : null}
    </PanelState>
  );
}

function Metric({ label, value, accent = false }: { label: string; value: number | string; accent?: boolean }) {
  return <div className={accent ? "accent" : ""}><span>{label}</span><strong>{typeof value === "number" ? number.format(value) : value}</strong></div>;
}

function UsageBreakdown({ title, values }: { title: string; values: Record<string, UsageCounts> }) {
  const rows = Object.entries(values);
  if (!rows.length) return null;
  return (
    <details className="usage-breakdown" open>
      <summary>{title}</summary>
      <div className="term-table-wrap">
        <table className="advanced-table">
          <thead><tr><th>分类</th><th>调用</th><th>输入</th><th>输出</th><th>总计</th></tr></thead>
          <tbody>{rows.map(([key, value]) => <tr key={key}><td><strong>{key}</strong></td><td>{number.format(value.calls)}</td><td>{number.format(value.input_tokens)}</td><td>{number.format(value.output_tokens)}</td><td>{number.format(value.total_tokens)}</td></tr>)}</tbody>
        </table>
      </div>
    </details>
  );
}
