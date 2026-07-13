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
  error?: string | null;
  updated_at: string;
};

export type Tier = {
  model: string;
  thinking: boolean;
};

export type Settings = {
  base_url: string;
  api_key: string;
  has_api_key?: boolean;
  timeout: number;
  max_retries: number;
  strong: Tier;
  cheap: Tier;
  fast: Tier;
  mono: boolean;
  bilingual: boolean;
  bilingual_order: string;
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
    throw new Error(body.detail || "请求失败");
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
