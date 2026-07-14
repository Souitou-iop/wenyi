export type Book = {
  id: string;
  filename: string;
  title: string;
  group_id: string | null;
  metadata: {
    authors: string[];
    language: string;
    publisher: string;
    publicationDate: string;
    identifier: string;
    description: string;
    subjects: string[];
    chapterCount: number;
    fileSize: number;
    coverUrl: string | null;
  };
};

export type Group = {
  id: string;
  name: string;
  book_count: number;
};

export type ConnectionTest = {
  ok: true;
  mode: "models" | "completion";
  latency_ms: number;
  checked_models: string[];
};

export type Task = {
  id: string;
  book_id: string;
  title: string;
  status: "running" | "paused" | "failed" | "completed";
  phase: string;
  label: string;
  fraction: number | null;
  completed: number;
  total: number;
  outputs: string[];
  workspace_ready?: boolean;
  phase_code?: string;
  outputs_stale?: boolean;
  error?: string | null;
  updated_at: string;
};

export type ChapterSummary = {
  index: number;
  title: string;
  title_translated: string;
  status: "pending" | "done";
  segment_count: number;
  review_complete: boolean;
};

export type ChapterDetail = {
  index: number;
  title: string;
  title_translated: string;
  status: "pending" | "done";
  review_complete: boolean;
  source_digest: string;
  segments: {
    index: number;
    source: string;
    target: string;
    kind: string;
  }[];
  review_issues: unknown[];
  backtranslation_issues: unknown[];
};

export type Analysis = {
  genre: string;
  tone: string;
  narration: string;
  pacing: string;
  dialogue_style: string;
  rhetoric: string;
  characters: unknown[];
  style_guide: string;
  book_synopsis: string;
  chapter_summaries: unknown[];
};

export type GlossaryTerm = {
  source: string;
  target: string;
  reading: string;
  type: string;
  gender: string;
  note: string;
  status: string;
};

export type GlossaryConflict = {
  id: number;
  source: string;
  current: string;
  proposed: string;
  reason: string;
};

export type UsageCounts = {
  calls: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cache_hits?: number;
  cache_misses?: number;
};

export type Usage = {
  totals: UsageCounts;
  by_tier: Record<string, UsageCounts>;
  by_stage: Record<string, UsageCounts>;
};

export type TaskEvent = {
  type?: string;
  phase?: string;
  phase_code?: string;
  message?: string;
  timestamp?: string;
  ts?: string;
  [key: string]: unknown;
};

export type TaskExport = {
  id: string;
  format: "epub" | "txt";
  mode: string;
  bilingual_order: string;
  about_page: boolean;
  status: "pending" | "completed" | "failed";
  size: number;
  created_at: string;
  error: string | null;
  filename: string;
  download_url: string | null;
  historical: boolean;
};

type WorkspaceResponse = { workspace_ready: boolean };

export type Tier = {
  model: string;
  thinking: boolean;
};

export type Provider =
  | "deepseek"
  | "openai"
  | "openrouter"
  | "openai-compatible"
  | "ollama"
  | "vllm";

export type ReasoningStyle = "none" | "deepseek" | "openai" | "openrouter";

export type Settings = {
  provider: Provider;
  base_url: string;
  api_key: string;
  has_api_key?: boolean;
  reasoning_style: ReasoningStyle;
  glow_mode: "none" | "symmetric" | "corners";
  source_lang: string;
  output_format: "epub" | "txt";
  timeout: number;
  max_retries: number;
  strong: Tier;
  cheap: Tier;
  fast: Tier;
  mono: boolean;
  bilingual: boolean;
  bilingual_order: "target_first" | "source_first";
  polish: boolean;
  review: boolean;
  autofix_severe: boolean;
  book_understanding: boolean;
  consistency_qa: boolean;
  about_page: boolean;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: "请求失败" }));
    const message = typeof body.detail === "string"
      ? body.detail
      : Array.isArray(body.detail)
        ? body.detail
          .map((item: { msg?: string }) => item.msg?.replace(/^Value error,\s*/, ""))
          .filter(Boolean)
          .join("；")
        : "";
    throw new Error(message || "请求失败");
  }
  return response.json() as Promise<T>;
}

export const api = {
  books: () => request<Book[]>("/api/books"),
  groups: () => request<Group[]>("/api/groups"),
  tasks: () => request<Task[]>("/api/tasks"),
  settings: () => request<Settings>("/api/settings"),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Book>("/api/books", { method: "POST", body: form });
  },
  removeBook: (id: string) => request(`/api/books/${id}`, { method: "DELETE" }),
  createGroup: (name: string) =>
    request<Group>("/api/groups", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),
  renameGroup: (id: string, name: string) =>
    request<Group>(`/api/groups/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),
  removeGroup: (id: string) => request(`/api/groups/${id}`, { method: "DELETE" }),
  moveBook: (id: string, groupId: string | null) =>
    request<Book>(`/api/books/${id}/group`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ group_id: groupId }),
    }),
  start: (bookId: string) =>
    request<Task>("/api/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ book_id: bookId }),
    }),
  stop: (id: string) => request<Task>(`/api/tasks/${id}/stop`, { method: "POST" }),
  resume: (id: string) => request<Task>(`/api/tasks/${id}/resume`, { method: "POST" }),
  chapters: (id: string) =>
    request<WorkspaceResponse & { editable: boolean; chapters: ChapterSummary[] }>(
      `/api/tasks/${id}/chapters`,
    ),
  chapter: (id: string, chapter: number) =>
    request<WorkspaceResponse & { editable: boolean; chapter: ChapterDetail }>(
      `/api/tasks/${id}/chapters/${chapter}`,
    ),
  saveSegment: (id: string, chapter: number, segment: number, target: string) =>
    request<{ saved: boolean; outputs_stale: boolean }>(
      `/api/tasks/${id}/chapters/${chapter}/segments/${segment}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target }),
      },
    ),
  completeReview: (id: string, chapter: number) =>
    request<{ saved: boolean; review_complete: boolean }>(
      `/api/tasks/${id}/chapters/${chapter}/review-complete`,
      { method: "POST" },
    ),
  analysis: (id: string) =>
    request<WorkspaceResponse & { editable: boolean; analysis: Analysis | null }>(
      `/api/tasks/${id}/analysis`,
    ),
  saveAnalysis: (id: string, values: Pick<Analysis, "style_guide" | "book_synopsis">) =>
    request<WorkspaceResponse & { editable: boolean; analysis: Analysis | null }>(
      `/api/tasks/${id}/analysis`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      },
    ),
  glossaryTerms: (id: string, query = "", type = "") => {
    const params = new URLSearchParams();
    if (query) params.set("q", query);
    if (type) params.set("type", type);
    const suffix = params.size ? `?${params}` : "";
    return request<WorkspaceResponse & { editable: boolean; terms: GlossaryTerm[] }>(
      `/api/tasks/${id}/glossary/terms${suffix}`,
    );
  },
  addGlossaryTerm: (id: string, term: Partial<GlossaryTerm>) =>
    request<GlossaryTerm>(`/api/tasks/${id}/glossary/terms`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(term),
    }),
  removeGlossaryTerm: (id: string, source: string) =>
    request<{ deleted: boolean }>(
      `/api/tasks/${id}/glossary/terms/${encodeURIComponent(source)}`,
      { method: "DELETE" },
    ),
  glossaryConflicts: (id: string) =>
    request<{ conflicts: GlossaryConflict[] }>(`/api/tasks/${id}/glossary/conflicts`),
  resolveGlossaryConflict: (id: string, conflictId: number, choice: "current" | "proposed") =>
    request<GlossaryTerm>(
      `/api/tasks/${id}/glossary/conflicts/${conflictId}/resolve`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ choice }),
      },
    ),
  usage: (id: string) =>
    request<WorkspaceResponse & { usage: Usage; has_usage: boolean; cache_available: boolean }>(
      `/api/tasks/${id}/usage`,
    ),
  taskEvents: (id: string, type = "", limit = 200) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (type) params.set("type", type);
    return request<WorkspaceResponse & { events: TaskEvent[]; types: string[] }>(
      `/api/tasks/${id}/events?${params}`,
    );
  },
  exports: (id: string) =>
    request<WorkspaceResponse & { outputs_stale: boolean; exports: TaskExport[] }>(
      `/api/tasks/${id}/exports`,
    ),
  createExport: (
    id: string,
    options: {
      format: "epub" | "txt";
      mono: boolean;
      bilingual: boolean;
      bilingual_order: "source_first" | "target_first";
      about_page: boolean;
    },
  ) =>
    request<TaskExport>(`/api/tasks/${id}/exports`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(options),
    }),
  saveSettings: (settings: Settings) =>
    request("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings),
    }),
  testConnection: (settings: Settings) =>
    request<ConnectionTest>("/api/settings/test-connection", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider: settings.provider,
        base_url: settings.base_url,
        api_key: settings.api_key,
        models: {
          strong: settings.strong.model,
          cheap: settings.cheap.model,
          fast: settings.fast.model,
        },
      }),
    }),
};
