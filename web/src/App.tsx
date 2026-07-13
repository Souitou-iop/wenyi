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
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type Book, type ConnectionTest, type Group, type Settings, type Task } from "./api";

const formatter = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 1 });

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

  const activeTask = useMemo(
    () => tasks.find((task) => task.status === "running") ?? tasks[0] ?? null,
    [tasks],
  );
  const currentBook = books.find((book) => book.id === selectedBook) ?? books[0] ?? null;
  const currentTask = currentBook
    ? tasks.find((task) => task.book_id === currentBook.id) ?? null
    : null;

  useEffect(() => {
    if (!activeTask) return;
    const events = new EventSource(`/api/tasks/${activeTask.id}/events`);
    events.onmessage = (message) => {
      const event = JSON.parse(message.data);
      if (event.type === "snapshot") {
        setTasks((current) =>
          current.map((task) => (task.id === event.task.id ? event.task : task)),
        );
      } else {
        void api.tasks().then(setTasks);
      }
    };
    return () => events.close();
  }, [activeTask?.id]);

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

  return (
    <main className="app-shell">
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
                  <div className="primary-actions">
                    <button className="button primary" disabled={busy} onClick={run}>
                      <Play weight="fill" />
                      {busy ? "准备中" : "开始翻译"}
                    </button>
                  </div>
                  <dl className="metadata-grid">
                    {currentBook.metadata.publisher ? (
                      <div><dt>出版社</dt><dd>{currentBook.metadata.publisher}</dd></div>
                    ) : null}
                    {currentBook.metadata.publicationDate ? (
                      <div><dt>出版日期</dt><dd>{currentBook.metadata.publicationDate}</dd></div>
                    ) : null}
                    {currentBook.metadata.identifier ? (
                      <div><dt>ISBN / 标识符</dt><dd>{currentBook.metadata.identifier}</dd></div>
                    ) : null}
                    {currentBook.metadata.language ? (
                      <div><dt>语言</dt><dd>{currentBook.metadata.language}</dd></div>
                    ) : null}
                    {currentBook.metadata.subjects?.length ? (
                      <div className="metadata-wide">
                        <dt>主题</dt><dd>{currentBook.metadata.subjects.join("、")}</dd>
                      </div>
                    ) : null}
                    {currentBook.metadata.chapterCount ? (
                      <div><dt>章节</dt><dd>{currentBook.metadata.chapterCount} 章</dd></div>
                    ) : null}
                    {currentBook.metadata.fileSize ? (
                      <div><dt>文件大小</dt><dd>{formatBytes(currentBook.metadata.fileSize)}</dd></div>
                    ) : null}
                  </dl>
                  {currentBook.metadata.description ? (
                    <section className="book-description">
                      <h2>内容简介</h2>
                      <p>{currentBook.metadata.description}</p>
                    </section>
                  ) : null}
                  {currentTask ? <CompactTaskStatus task={currentTask} /> : null}
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
            onClose={() => setSettingsOpen(false)}
            onSave={async (next) => {
              await api.saveSettings(next);
              setSettings(next);
              setSettingsOpen(false);
            }}
          />
        ) : null}
      </AnimatePresence>
    </main>
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
        <span className="brand-mark">
          <img src="/wenyi-logo-v2.png" alt="" />
        </span>
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

function CompactTaskStatus({ task }: { task: Task }) {
  const fraction = task.fraction ?? (task.total ? task.completed / task.total : 0);
  const progress = Math.round(Math.min(1, Math.max(0, fraction)) * 100);
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
          <button className="button quiet" onClick={() => void api.stop(task.id).then(() => location.reload())}>
            <Pause weight="fill" /> 暂停
          </button>
        ) : task.status !== "completed" ? (
          <button className="button quiet" onClick={() => void api.resume(task.id).then(() => location.reload())}>
            <Play weight="fill" /> 继续
          </button>
        ) : (
          <span className="compact-task-complete">
            <Check weight="bold" /> 翻译已完成
          </span>
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
  onClose,
  onSave,
}: {
  settings: Settings;
  onClose: () => void;
  onSave: (settings: Settings) => Promise<void>;
}) {
  const [draft, setDraft] = useState(settings);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [connection, setConnection] = useState<ConnectionTest | null>(null);
  const [connectionError, setConnectionError] = useState("");
  const update = <K extends keyof Settings>(key: K, value: Settings[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
    setConnection(null);
    setConnectionError("");
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

  return (
    <>
      <motion.button
        className="sheet-scrim"
        aria-label="关闭设置"
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
            <h2>连接你的模型</h2>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="关闭设置">
            <X />
          </button>
        </header>
        <div className="settings-body">
          <label>
            <span>OpenAI 兼容端点</span>
            <input value={draft.base_url} onChange={(event) => update("base_url", event.target.value)} />
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
          {(["strong", "cheap", "fast"] as const).map((tier) => (
            <label key={tier}>
              <span>{tier} 模型</span>
              <input
                value={draft[tier].model}
                onChange={(event) =>
                  (() => {
                    setDraft((current) => ({
                      ...current,
                      [tier]: { ...current[tier], model: event.target.value },
                    }));
                    setConnection(null);
                    setConnectionError("");
                  })()
                }
              />
            </label>
          ))}
          <div className="toggle-grid">
            {([
              ["polish", "润色"],
              ["review", "审校"],
              ["book_understanding", "全书理解"],
              ["consistency_qa", "一致性检查"],
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
        </div>
        <footer>
          <button className="button quiet" onClick={onClose}>取消</button>
          <button
            className="button primary"
            disabled={saving}
            onClick={() => {
              setSaving(true);
              void onSave(draft).finally(() => setSaving(false));
            }}
          >
            <Check weight="bold" />
            {saving ? "保存中" : "保存设置"}
          </button>
        </footer>
      </motion.aside>
    </>
  );
}

export default App;
