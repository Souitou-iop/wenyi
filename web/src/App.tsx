import {
  BookOpenText,
  Books,
  Check,
  DownloadSimple,
  FolderSimple,
  GearSix,
  Pause,
  PencilSimple,
  Play,
  Plug,
  Plus,
  SpinnerGap,
  Trash,
  UploadSimple,
  X,
} from "@phosphor-icons/react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useState } from "react";
import {
  api,
  type Book,
  type ConnectionTest,
  type Group,
  type Provider,
  type Settings,
  type Task,
} from "./api";
import AdvancedWorkspace from "./AdvancedWorkspace";

const formatter = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 1 });
const glowModes: { id: Settings["glow_mode"]; label: string }[] = [
  { id: "none", label: "无高光" },
  { id: "symmetric", label: "上下对称" },
  { id: "corners", label: "对角边框" },
];
const sourceLanguages = [
  ["auto", "自动识别"],
  ["ja", "日语"],
  ["en", "英语"],
  ["ko", "韩语"],
  ["ru", "俄语"],
  ["fr", "法语"],
  ["de", "德语"],
  ["es", "西班牙语"],
  ["pt", "葡萄牙语"],
  ["it", "意大利语"],
] as const;
const tierLabels = {
  strong: "强档",
  cheap: "经济档",
  fast: "快速档",
} as const;
const providers: { id: Provider; label: string }[] = [
  { id: "deepseek", label: "DeepSeek" },
  { id: "openai", label: "OpenAI" },
  { id: "openrouter", label: "OpenRouter" },
  { id: "openai-compatible", label: "OpenAI 兼容端点" },
  { id: "ollama", label: "Ollama" },
  { id: "vllm", label: "vLLM" },
];

function statusLabel(status: Task["status"]) {
  return {
    running: "翻译中",
    paused: "已暂停",
    failed: "需要处理",
    completed: "已完成",
  }[status];
}

function formatBytes(value = 0) {
  if (!value) return "未知大小";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${formatter.format(value / 1024)} KB`;
  return `${formatter.format(value / 1024 / 1024)} MB`;
}

function BookCover({
  src,
  alt,
  className,
  selected = false,
}: {
  src: string | null;
  alt: string;
  className: string;
  selected?: boolean;
}) {
  const [failed, setFailed] = useState(false);

  if (!src || failed) {
    return (
      <span className={`${className} cover-placeholder`} role="img" aria-label={`${alt}占位图`}>
        <Books weight={selected ? "fill" : "duotone"} />
      </span>
    );
  }

  return (
    <span className={className}>
      <img src={src} alt={alt} loading="lazy" onError={() => setFailed(true)} />
    </span>
  );
}

function App() {
  const [books, setBooks] = useState<Book[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [selectedBook, setSelectedBook] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [glowSaving, setGlowSaving] = useState(false);
  const [taskActions, setTaskActions] = useState<Record<string, "stop" | "resume">>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [nextBooks, nextGroups, nextTasks, nextSettings] = await Promise.all([
        api.books(),
        api.groups(),
        api.tasks(),
        api.settings(),
      ]);
      setBooks(nextBooks);
      setGroups(nextGroups);
      setTasks(nextTasks);
      setSettings(nextSettings);
      setSelectedBook((current) => current ?? nextBooks[0]?.id ?? null);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "服务暂不可用");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const runningTaskIds = tasks
    .filter((task) => task.status === "running")
    .map((task) => task.id)
    .sort()
    .join(",");
  const currentBook = books.find((book) => book.id === selectedBook) ?? books[0] ?? null;
  const currentTask = currentBook
    ? tasks.find((task) => task.book_id === currentBook.id) ?? null
    : null;
  const glowMode = settings?.glow_mode ?? "none";
  const glowModeIndex = glowModes.findIndex((mode) => mode.id === glowMode);

  useEffect(() => {
    if (!runningTaskIds) return;
    const streams = runningTaskIds.split(",").map((taskId) => {
      const events = new EventSource(`/api/tasks/${taskId}/stream`);
      events.onmessage = (message) => {
        const event = JSON.parse(message.data);
        if (event.type === "snapshot") {
          setTasks((current) =>
            current.map((task) => (task.id === event.task.id ? event.task : task)),
          );
        } else {
          void api.tasks()
            .then(setTasks)
            .catch((reason) => {
              setError(reason instanceof Error ? reason.message : "无法刷新任务状态");
            });
        }
      };
      return events;
    });
    return () => streams.forEach((events) => events.close());
  }, [runningTaskIds]);

  const run = async () => {
    if (!currentBook) return;
    setBusy(true);
    try {
      const task = await api.start(currentBook.id);
      setTasks((current) => [task, ...current]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法启动任务");
    } finally {
      setBusy(false);
    }
  };

  const updateTask = async (action: "stop" | "resume", task: Task) => {
    if (taskActions[task.id]) return;
    setTaskActions((current) => ({ ...current, [task.id]: action }));
    try {
      const nextTask = await api[action](task.id);
      setTasks((current) =>
        current.map((currentTask) => (currentTask.id === nextTask.id ? nextTask : currentTask)),
      );
      setError("");
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : action === "stop"
            ? "无法暂停任务"
            : "无法继续任务",
      );
    } finally {
      setTaskActions((current) => {
        const next = { ...current };
        delete next[task.id];
        return next;
      });
    }
  };

  const upload = async (file: File) => {
    setBusy(true);
    try {
      const book = await api.upload(file);
      setBooks((current) => [book, ...current]);
      setSelectedBook(book.id);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "导入失败");
    } finally {
      setBusy(false);
    }
  };

  const reportFailure = async (reason: unknown, fallback: string) => {
    await refresh();
    setError(reason instanceof Error ? reason.message : fallback);
  };

  const moveBook = async (bookId: string, groupId: string | null) => {
    const previous = books;
    setBooks((current) =>
      current.map((book) => (book.id === bookId ? { ...book, group_id: groupId } : book)),
    );
    try {
      await api.moveBook(bookId, groupId);
      await refresh();
    } catch (reason) {
      setBooks(previous);
      await reportFailure(reason, "无法移动图书");
    }
  };

  const createGroup = async (name: string) => {
    try {
      const group = await api.createGroup(name);
      setGroups((current) => [...current, group]);
      setError("");
    } catch (reason) {
      await reportFailure(reason, "无法创建分组");
      throw reason;
    }
  };

  const renameGroup = async (id: string, name: string) => {
    const previous = groups;
    setGroups((current) =>
      current.map((group) => (group.id === id ? { ...group, name } : group)),
    );
    try {
      await api.renameGroup(id, name);
      await refresh();
    } catch (reason) {
      setGroups(previous);
      await reportFailure(reason, "无法重命名分组");
      throw reason;
    }
  };

  const removeGroup = async (id: string) => {
    const previousGroups = groups;
    const previousBooks = books;
    setGroups((current) => current.filter((group) => group.id !== id));
    setBooks((current) =>
      current.map((book) => (book.group_id === id ? { ...book, group_id: null } : book)),
    );
    try {
      await api.removeGroup(id);
      await refresh();
    } catch (reason) {
      setGroups(previousGroups);
      setBooks(previousBooks);
      await reportFailure(reason, "无法删除分组");
    }
  };

  const changeGlowMode = async () => {
    if (!settings || glowSaving) return;
    const nextMode = glowModes[(glowModeIndex + 1) % glowModes.length].id;
    const previous = settings;
    const next = { ...settings, glow_mode: nextMode };
    setSettings(next);
    setGlowSaving(true);
    try {
      await api.saveSettings(next);
      setError("");
    } catch (reason) {
      setSettings(previous);
      setError(reason instanceof Error ? reason.message : "无法保存高光设置");
    } finally {
      setGlowSaving(false);
    }
  };

  return (
    <main className="app-shell" data-glow-mode={glowMode}>
      <TopBar
        running={tasks.filter((task) => task.status === "running").length}
        onSettings={() => setSettingsOpen(true)}
      />
      <div className="ambient ambient-one" />
      <div className="ambient ambient-two" />

      <section className="workspace">
        <LibraryRail
          books={books}
          groups={groups}
          selected={currentBook?.id ?? null}
          onSelect={setSelectedBook}
          onUpload={upload}
          onRemove={async (id) => {
            const task = tasks.find((candidate) => candidate.book_id === id);
            const message = task && task.status !== "running"
              ? "确定删除这本书吗？关联的任务记录、状态和内部产物也会一并删除。"
              : "确定删除这本书吗？此操作无法撤销。";
            if (!window.confirm(message)) return;
            try {
              await api.removeBook(id);
              await refresh();
            } catch (reason) {
              await reportFailure(reason, "无法删除图书");
            }
          }}
          onCreateGroup={createGroup}
          onRenameGroup={renameGroup}
          onRemoveGroup={removeGroup}
          onMoveBook={moveBook}
        />

        <section className="focus-panel">
          <AnimatePresence mode="wait">
            {currentBook ? (
              <motion.div
                key={currentBook.id}
                initial={{ opacity: 0, y: 18 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -12 }}
                transition={{ type: "spring", bounce: 0, duration: 0.38 }}
                className="book-focus"
              >
                <BookCover
                  src={currentBook.metadata.coverUrl}
                  alt={`《${currentBook.title}》封面`}
                  className="detail-cover"
                />
                <div className="book-details">
                  <div className="book-heading">
                    {currentBook.metadata.authors?.length ? (
                      <p className="context-line">{currentBook.metadata.authors.join("、")}</p>
                    ) : null}
                    <h1>{currentBook.title}</h1>
                  </div>
                  {!currentTask ? (
                    <div className="primary-actions">
                      <button className="button primary" disabled={busy} onClick={run}>
                        <Play weight="fill" />
                        {busy ? "准备中" : "开始翻译"}
                      </button>
                    </div>
                  ) : null}
                  {currentTask ? (
                    <AdvancedWorkspace
                      key={currentTask.id}
                      task={currentTask}
                      onError={setError}
                      overview={(
                        <div className="overview-panel">
                          <BookOverview book={currentBook} />
                          <CompactTaskStatus
                            task={currentTask}
                            busy={busy}
                            pendingAction={taskActions[currentTask.id] ?? ""}
                            onStop={() => void updateTask("stop", currentTask)}
                            onResume={() => void updateTask("resume", currentTask)}
                            onRetranslate={() => void run()}
                          />
                        </div>
                      )}
                    />
                  ) : (
                    <BookOverview book={currentBook} />
                  )}
                </div>
              </motion.div>
            ) : (
              <EmptyWorkspace onUpload={upload} busy={busy} />
            )}
          </AnimatePresence>
        </section>
      </section>

      {error ? (
        <button className="error-banner" onClick={() => setError("")}>
          <span>{error}</span>
          <X />
        </button>
      ) : null}

      <AnimatePresence>
        {settingsOpen && settings ? (
          <SettingsSheet
            settings={settings}
            glowSaving={glowSaving}
            onClose={() => setSettingsOpen(false)}
            onGlowMode={() => void changeGlowMode()}
            onSave={async (next) => {
              await api.saveSettings(next);
              setSettings({
                ...next,
                api_key: "",
                has_api_key: Boolean(next.api_key) || next.has_api_key,
              });
              setSettingsOpen(false);
            }}
          />
        ) : null}
      </AnimatePresence>
    </main>
  );
}

function BookOverview({ book }: { book: Book }) {
  return (
    <>
      <dl className="metadata-grid">
        {book.metadata.publisher ? <div><dt>出版社</dt><dd>{book.metadata.publisher}</dd></div> : null}
        {book.metadata.publicationDate ? <div><dt>出版日期</dt><dd>{book.metadata.publicationDate}</dd></div> : null}
        {book.metadata.identifier ? <div><dt>ISBN / 标识符</dt><dd>{book.metadata.identifier}</dd></div> : null}
        {book.metadata.language ? <div><dt>语言</dt><dd>{book.metadata.language}</dd></div> : null}
        {book.metadata.subjects?.length ? <div className="metadata-wide"><dt>主题</dt><dd>{book.metadata.subjects.join("、")}</dd></div> : null}
        {book.metadata.chapterCount ? <div><dt>章节</dt><dd>{book.metadata.chapterCount} 章</dd></div> : null}
        {book.metadata.fileSize ? <div><dt>文件大小</dt><dd>{formatBytes(book.metadata.fileSize)}</dd></div> : null}
      </dl>
      {book.metadata.description ? <section className="book-description"><h2>内容简介</h2><p>{book.metadata.description}</p></section> : null}
    </>
  );
}

function TopBar({
  running,
  onSettings,
}: {
  running: number;
  onSettings: () => void;
}) {
  return (
    <header className="topbar">
      <a className="brand" href="#top" aria-label="文译工作台">
        <span>文译</span>
      </a>
      <div className="topbar-actions">
        <span className="running-state">{running ? `${running} 项正在运行` : "本机服务已就绪"}</span>
        <button className="icon-button" onClick={onSettings} aria-label="打开设置">
          <GearSix />
        </button>
      </div>
    </header>
  );
}

function LibraryRail({
  books,
  groups,
  selected,
  onSelect,
  onUpload,
  onRemove,
  onCreateGroup,
  onRenameGroup,
  onRemoveGroup,
  onMoveBook,
}: {
  books: Book[];
  groups: Group[];
  selected: string | null;
  onSelect: (id: string) => void;
  onUpload: (file: File) => void;
  onRemove: (id: string) => Promise<void>;
  onCreateGroup: (name: string) => Promise<void>;
  onRenameGroup: (id: string, name: string) => Promise<void>;
  onRemoveGroup: (id: string) => Promise<void>;
  onMoveBook: (bookId: string, groupId: string | null) => Promise<void>;
}) {
  const [creating, setCreating] = useState(false);
  const [newGroupName, setNewGroupName] = useState("");
  const [editingGroup, setEditingGroup] = useState<string | null>(null);
  const [groupName, setGroupName] = useState("");
  const [draggedBook, setDraggedBook] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null | undefined>(undefined);

  const createGroup = async () => {
    const name = newGroupName.trim();
    if (!name) return;
    try {
      await onCreateGroup(name);
    } catch {
      return;
    }
    setNewGroupName("");
    setCreating(false);
  };

  const cancelCreateGroup = () => {
    setNewGroupName("");
    setCreating(false);
  };

  const renameGroup = async (id: string) => {
    const name = groupName.trim();
    if (!name) return;
    try {
      await onRenameGroup(id, name);
    } catch {
      return;
    }
    setEditingGroup(null);
  };

  const dropBook = (bookId: string, groupId: string | null) => {
    if (!bookId) return;
    void onMoveBook(bookId, groupId);
    setDraggedBook(null);
    setDropTarget(undefined);
  };

  const renderBook = (book: Book) => (
    <div
      key={book.id}
      className={`book-row ${selected === book.id ? "selected" : ""}`}
      draggable
      onDragStart={(event) => {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", book.id);
        setDraggedBook(book.id);
      }}
      onDragEnd={() => {
        setDraggedBook(null);
        setDropTarget(undefined);
      }}
    >
      <button className="book-select" onClick={() => onSelect(book.id)}>
        <BookCover
          src={book.metadata.coverUrl}
          alt={`《${book.title}》封面`}
          className="book-glyph"
          selected={selected === book.id}
        />
        <span className="book-row-copy">
          <strong>{book.title}</strong>
          <small>
            {book.metadata.chapterCount || "?"} 章 / {formatBytes(book.metadata.fileSize)}
          </small>
        </span>
      </button>
      <div className="book-row-actions">
        <select
          className="mobile-group-select"
          aria-label={`移动《${book.title}》到分组`}
          value={book.group_id ?? ""}
          onChange={(event) => void onMoveBook(book.id, event.target.value || null)}
        >
          <option value="">未分组</option>
          {groups.map((group) => (
            <option key={group.id} value={group.id}>{group.name}</option>
          ))}
        </select>
        <button
          className="row-delete"
          aria-label={`删除《${book.title}》`}
          onClick={() => void onRemove(book.id)}
        >
          <Trash />
        </button>
      </div>
    </div>
  );

  const renderGroup = (group: Group | null) => {
    const id = group?.id ?? null;
    const groupBooks = books.filter((book) => (book.group_id ?? null) === id);
    const isDropTarget = dropTarget === id;
    return (
      <section
        key={id ?? "ungrouped"}
        className={`library-group ${isDropTarget ? "drop-target" : ""}`}
        onDragEnter={(event) => {
          event.preventDefault();
          setDropTarget(id);
        }}
        onDragOver={(event) => {
          event.preventDefault();
          event.dataTransfer.dropEffect = "move";
        }}
        onDragLeave={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
            setDropTarget(undefined);
          }
        }}
        onDrop={(event) => {
          event.preventDefault();
          dropBook(draggedBook ?? event.dataTransfer.getData("text/plain"), id);
        }}
      >
        <div className="group-heading">
          <div>
            <FolderSimple weight={group ? "fill" : "regular"} />
            {editingGroup === id && group ? (
              <input
                autoFocus
                value={groupName}
                aria-label="分组名称"
                onChange={(event) => setGroupName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void renameGroup(group.id);
                  if (event.key === "Escape") setEditingGroup(null);
                }}
              />
            ) : (
              <span>{group?.name ?? "未分组"}</span>
            )}
            <small>{groupBooks.length}</small>
          </div>
          {group ? (
            <div className="group-actions">
              <button
                aria-label={`重命名${group.name}`}
                onClick={() => {
                  setEditingGroup(group.id);
                  setGroupName(group.name);
                }}
              >
                <PencilSimple />
              </button>
              <button aria-label={`删除${group.name}`} onClick={() => void onRemoveGroup(group.id)}>
                <Trash />
              </button>
            </div>
          ) : null}
        </div>
        <div className="group-books">
          {groupBooks.map(renderBook)}
          {!groupBooks.length ? (
            <div className="empty-group">{draggedBook ? "松开以移入" : "拖拽图书到这里"}</div>
          ) : null}
        </div>
      </section>
    );
  };

  return (
    <aside className="library-rail">
      <div className="rail-heading">
        <div>
          <span>书架</span>
          <strong>{books.length}</strong>
        </div>
        <div className="rail-actions">
          <button
            className="icon-button small"
            aria-label="新建分组"
            onClick={() => setCreating(true)}
          >
            <FolderSimple />
          </button>
          <label className="icon-button small" aria-label="导入图书">
            <Plus />
            <input
              hidden
              type="file"
              accept=".epub,.fb2,.txt"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) onUpload(file);
                event.currentTarget.value = "";
              }}
            />
          </label>
        </div>
      </div>
      {creating ? (
        <div className="new-group-form">
          <input
            autoFocus
            value={newGroupName}
            placeholder="分组名称"
            onChange={(event) => setNewGroupName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void createGroup();
              if (event.key === "Escape") cancelCreateGroup();
            }}
          />
          <button className="button primary" onClick={() => void createGroup()}>创建</button>
          <button className="button quiet" onClick={cancelCreateGroup}>取消</button>
        </div>
      ) : null}
      <div className="group-track">
        {groups.map((group) => renderGroup(group))}
        {renderGroup(null)}
      </div>
      {!books.length ? <p className="rail-empty">导入 EPUB、FB2 或 TXT 开始。</p> : null}
    </aside>
  );
}

function CompactTaskStatus({
  task,
  busy,
  pendingAction,
  onStop,
  onResume,
  onRetranslate,
}: {
  task: Task;
  busy: boolean;
  pendingAction: "" | "stop" | "resume";
  onStop: () => void;
  onResume: () => void;
  onRetranslate: () => void;
}) {
  const fraction = task.fraction ?? (task.total ? task.completed / task.total : 0);
  const progress = Math.round(Math.min(1, Math.max(0, fraction)) * 100);
  const stopping = pendingAction === "stop";
  const resuming = pendingAction === "resume";
  return (
    <section className={`compact-task-status ${task.status}`}>
      <div className="compact-task-heading">
        <div>
          <span>{statusLabel(task.status)}</span>
          <strong>{task.phase || task.label || "翻译任务"}</strong>
        </div>
        <strong>{progress}%</strong>
      </div>
      <div
        className="compact-progress"
        role="progressbar"
        aria-label="翻译进度"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progress}
      >
        <span style={{ width: `${progress}%` }} />
      </div>
      {task.label && task.label !== task.phase ? <p>{task.label}</p> : null}
      {task.error ? <p className="compact-task-error">{task.error}</p> : null}
      <div className="task-controls">
        {task.status === "running" ? (
          <button className="button quiet" disabled={Boolean(pendingAction)} onClick={onStop}>
            {stopping ? <SpinnerGap className="spin" /> : <Pause weight="fill" />}
            {stopping ? "暂停中…" : "暂停"}
          </button>
        ) : task.status !== "completed" ? (
          <button className="button quiet" disabled={Boolean(pendingAction)} onClick={onResume}>
            {resuming ? <SpinnerGap className="spin" /> : <Play weight="fill" />}
            {resuming ? "继续中…" : "继续"}
          </button>
        ) : (
          <>
            <span className="compact-task-complete">
              <Check weight="bold" /> 翻译已完成
            </span>
            <button
              className="button quiet"
              disabled={busy || Boolean(pendingAction)}
              onClick={onRetranslate}
            >
              {busy ? <SpinnerGap className="spin" /> : <Play weight="fill" />}
              {busy ? "准备中…" : "重新翻译"}
            </button>
          </>
        )}
        {task.outputs.map((output) => (
          <a
            key={output}
            className="button quiet"
            href={`/api/tasks/${task.id}/outputs/${encodeURIComponent(output.split(/[/\\]/).pop() || "")}`}
          >
            <DownloadSimple /> 下载译文
          </a>
        ))}
      </div>
    </section>
  );
}

function EmptyWorkspace({ onUpload, busy }: { onUpload: (file: File) => void; busy: boolean }) {
  const [dragging, setDragging] = useState(false);
  return (
    <div className="empty-workspace">
      <div className="empty-symbol">
        <BookOpenText weight="duotone" />
      </div>
      <h1>把一本书交给文译。</h1>
      <p>原文件保留不动，翻译断点、术语和产物独立保存。</p>
      <label
        className={`drop-zone ${dragging ? "dragging" : ""}`}
        onDragEnter={() => setDragging(true)}
        onDragLeave={() => setDragging(false)}
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          const file = event.dataTransfer.files[0];
          if (file) onUpload(file);
        }}
      >
        <UploadSimple />
        <span>{busy ? "正在导入" : "选择或拖入图书"}</span>
        <input
          hidden
          type="file"
          accept=".epub,.fb2,.txt"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) onUpload(file);
          }}
        />
      </label>
    </div>
  );
}

function SettingsSheet({
  settings,
  glowSaving,
  onClose,
  onGlowMode,
  onSave,
}: {
  settings: Settings;
  glowSaving: boolean;
  onClose: () => void;
  onGlowMode: () => void;
  onSave: (settings: Settings) => Promise<void>;
}) {
  const [draft, setDraft] = useState(settings);
  const [page, setPage] = useState<"model" | "webui">("model");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [connection, setConnection] = useState<ConnectionTest | null>(null);
  const [connectionError, setConnectionError] = useState("");
  const [saveError, setSaveError] = useState("");
  const outputMissing = !draft.mono && !draft.bilingual;
  const compatibleReasoning = ["openai-compatible", "ollama", "vllm"].includes(
    draft.provider,
  );

  const update = <K extends keyof Settings>(key: K, value: Settings[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
    setConnection(null);
    setConnectionError("");
    setSaveError("");
  };

  const updateTier = (
    tier: "strong" | "cheap" | "fast",
    value: Partial<Settings[typeof tier]>,
  ) => {
    setDraft((current) => ({
      ...current,
      [tier]: { ...current[tier], ...value },
    }));
    setConnection(null);
    setConnectionError("");
    setSaveError("");
  };

  const updateProvider = (provider: Provider) => {
    setDraft((current) => ({
      ...current,
      provider,
      api_key: "",
      has_api_key: provider === settings.provider ? settings.has_api_key : false,
    }));
    setConnection(null);
    setConnectionError("");
    setSaveError("");
  };

  const testConnection = async () => {
    setTesting(true);
    setConnection(null);
    setConnectionError("");
    try {
      setConnection(await api.testConnection(draft));
    } catch (reason) {
      setConnectionError(reason instanceof Error ? reason.message : "连接检测失败");
    } finally {
      setTesting(false);
    }
  };

  const saveSettings = async () => {
    if (outputMissing) return;
    setSaving(true);
    setSaveError("");
    try {
      await onSave({ ...draft, glow_mode: settings.glow_mode });
    } catch (reason) {
      setSaveError(reason instanceof Error ? reason.message : "无法保存设置");
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <motion.button
        className="sheet-scrim"
        aria-label="关闭设置"
        disabled={saving}
        onClick={onClose}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
      />
      <motion.aside
        className="settings-sheet"
        initial={{ x: "104%" }}
        animate={{ x: 0 }}
        exit={{ x: "104%" }}
        transition={{ type: "spring", bounce: 0, duration: 0.42 }}
      >
        <header>
          <div>
            <span>设置</span>
            <h2>{page === "model" ? "模型配置" : "WebUI 设置"}</h2>
          </div>
          <button className="icon-button" disabled={saving} onClick={onClose} aria-label="关闭设置">
            <X />
          </button>
        </header>
        <nav className="settings-pages" aria-label="设置页面">
          <button
            className={page === "model" ? "active" : ""}
            aria-pressed={page === "model"}
            onClick={() => setPage("model")}
          >
            模型配置
          </button>
          <button
            className={page === "webui" ? "active" : ""}
            aria-pressed={page === "webui"}
            onClick={() => setPage("webui")}
          >
            WebUI 设置
          </button>
        </nav>
        <div className="settings-body" key={page}>
          {page === "model" ? (
            <>
              <section className="settings-section">
                <div className="settings-section-heading">
                  <strong>模型服务</strong>
                  <span>选择服务类型并验证三档模型。</span>
                </div>
                <label>
                  <span>服务类型</span>
                  <select
                    value={draft.provider}
                    onChange={(event) => updateProvider(event.target.value as Provider)}
                  >
                    {providers.map((provider) => (
                      <option key={provider.id} value={provider.id}>{provider.label}</option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>API 端点</span>
                  <input
                    value={draft.base_url}
                    onChange={(event) => update("base_url", event.target.value)}
                  />
                </label>
                <label>
                  <span>API Key</span>
                  <input
                    type="password"
                    value={draft.api_key}
                    placeholder={draft.has_api_key ? "已安全保存，留空保持不变" : "输入 API Key"}
                    onChange={(event) => update("api_key", event.target.value)}
                  />
                </label>
                {compatibleReasoning ? (
                  <label>
                    <span>思考参数协议</span>
                    <select
                      value={draft.reasoning_style}
                      onChange={(event) =>
                        update(
                          "reasoning_style",
                          event.target.value as Settings["reasoning_style"],
                        )
                      }
                    >
                      <option value="none">不转换</option>
                      <option value="deepseek">DeepSeek</option>
                      <option value="openai">OpenAI</option>
                      <option value="openrouter">OpenRouter</option>
                    </select>
                  </label>
                ) : null}
                <div className="connection-test">
                  <button className="button quiet" disabled={testing} onClick={() => void testConnection()}>
                    {testing ? <SpinnerGap className="spin" /> : <Plug />}
                    {testing ? "检测中…" : "检测连接"}
                  </button>
                  {connection ? (
                    <span className="connection-success">
                      <Check weight="bold" />
                      {connection.mode === "models"
                        ? `已验证 ${connection.checked_models.length} 个模型`
                        : `已通过 ${connection.checked_models[0]} 发起请求`}
                      {" · "}{connection.latency_ms}ms
                    </span>
                  ) : null}
                  {connectionError ? <span className="connection-error">{connectionError}</span> : null}
                </div>
              </section>

              <section className="settings-section">
                <div className="settings-section-heading">
                  <strong>模型档位</strong>
                  <span>
                    {compatibleReasoning
                      ? draft.reasoning_style === "none"
                        ? "思考开关仅调整 token 预算，不转换服务商请求参数。"
                        : `思考开关会转换为 ${draft.reasoning_style} 兼容协议。`
                      : "分别设置高质量、经济和快速任务使用的模型。"}
                  </span>
                </div>
                <div className="model-settings">
                  {(["strong", "cheap", "fast"] as const).map((tier) => (
                    <div className="model-setting" key={tier}>
                      <label>
                        <span>{tierLabels[tier]}模型</span>
                        <input
                          value={draft[tier].model}
                          onChange={(event) => updateTier(tier, { model: event.target.value })}
                        />
                      </label>
                      <label className="inline-toggle">
                        <span>思考模式</span>
                        <input
                          type="checkbox"
                          checked={draft[tier].thinking}
                          onChange={(event) => updateTier(tier, { thinking: event.target.checked })}
                        />
                      </label>
                    </div>
                  ))}
                </div>
              </section>

              <details className="settings-advanced">
                <summary>高级连接设置</summary>
                <div className="field-grid">
                  <label>
                    <span>请求超时（秒）</span>
                    <input
                      type="number"
                      min="1"
                      value={draft.timeout}
                      onChange={(event) => update("timeout", Number(event.target.value))}
                    />
                  </label>
                  <label>
                    <span>最大重试次数</span>
                    <input
                      type="number"
                      min="0"
                      value={draft.max_retries}
                      onChange={(event) => update("max_retries", Number(event.target.value))}
                    />
                  </label>
                </div>
              </details>
            </>
          ) : (
            <>
              <section className="settings-section">
                <div className="settings-section-heading">
                  <strong>语言与格式</strong>
                  <span>这些默认值会应用到新建翻译任务。</span>
                </div>
                <div className="field-grid">
                  <label>
                    <span>源语言</span>
                    <select
                      value={draft.source_lang}
                      onChange={(event) => update("source_lang", event.target.value)}
                    >
                      {!sourceLanguages.some(([value]) => value === draft.source_lang) ? (
                        <option value={draft.source_lang}>{draft.source_lang}</option>
                      ) : null}
                      {sourceLanguages.map(([value, label]) => (
                        <option value={value} key={value}>{label}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>目标语言</span>
                    <select value="zh" disabled>
                      <option value="zh">简体中文</option>
                    </select>
                  </label>
                  <label>
                    <span>文件格式</span>
                    <select
                      value={draft.output_format}
                      onChange={(event) =>
                        update("output_format", event.target.value as Settings["output_format"])
                      }
                    >
                      <option value="epub">EPUB</option>
                      <option value="txt">TXT</option>
                    </select>
                  </label>
                  <label>
                    <span>双语排列</span>
                    <select
                      value={draft.bilingual_order}
                      disabled={!draft.bilingual}
                      onChange={(event) =>
                        update("bilingual_order", event.target.value as Settings["bilingual_order"])
                      }
                    >
                      <option value="target_first">译文在上</option>
                      <option value="source_first">原文在上</option>
                    </select>
                  </label>
                </div>
                <div className="toggle-grid">
                  {([
                    ["mono", "单语版"],
                    ["bilingual", "双语版"],
                    ["about_page", "翻译说明页"],
                  ] as const).map(([key, label]) => (
                    <label className="toggle-row" key={key}>
                      <span>{label}</span>
                      <input
                        type="checkbox"
                        checked={draft[key]}
                        onChange={(event) => update(key, event.target.checked)}
                      />
                    </label>
                  ))}
                </div>
                {outputMissing ? (
                  <p className="settings-inline-error">单语版和双语版至少需要启用一种。</p>
                ) : null}
              </section>

              <section className="settings-section">
                <div className="settings-section-heading">
                  <strong>翻译流程</strong>
                  <span>控制质量、耗时和模型调用数量。</span>
                </div>
                <div className="toggle-grid">
                  {([
                    ["polish", "润色"],
                    ["review", "审校"],
                    ["autofix_severe", "自动修复严重问题"],
                    ["book_understanding", "全书理解"],
                    ["consistency_qa", "一致性检查"],
                  ] as const).map(([key, label]) => (
                    <label
                      className={`toggle-row ${key === "autofix_severe" && !draft.review ? "disabled" : ""}`}
                      key={key}
                    >
                      <span>{label}</span>
                      <input
                        type="checkbox"
                        checked={draft[key]}
                        disabled={key === "autofix_severe" && !draft.review}
                        onChange={(event) => {
                          update(key, event.target.checked);
                          if (key === "review" && !event.target.checked) {
                            update("autofix_severe", false);
                          }
                        }}
                      />
                    </label>
                  ))}
                </div>
              </section>

              <section className="settings-section">
                <div className="settings-section-heading">
                  <strong>界面</strong>
                  <span>点击后即时切换并自动保存。</span>
                </div>
                <button
                  className="glow-mode-toggle settings-glow-toggle"
                  disabled={glowSaving || saving}
                  onClick={onGlowMode}
                  aria-label={`切换卡片高光，当前为${glowModes.find((mode) => mode.id === settings.glow_mode)?.label}`}
                >
                  {glowSaving
                    ? "高光 · 保存中…"
                    : `高光 · ${glowModes.find((mode) => mode.id === settings.glow_mode)?.label}`}
                </button>
              </section>
            </>
          )}
        </div>
        <footer>
          {saveError ? <span className="settings-save-error" role="alert">{saveError}</span> : <span />}
          <div className="settings-footer-actions">
            <button className="button quiet" disabled={saving} onClick={onClose}>取消</button>
            <button
              className="button primary"
              disabled={saving || glowSaving || outputMissing}
              onClick={() => void saveSettings()}
            >
              <Check weight="bold" />
              {saving ? "保存中" : "保存设置"}
            </button>
          </div>
        </footer>
      </motion.aside>
    </>
  );
}

export default App;
