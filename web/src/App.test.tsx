import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type { Book, Settings, Task } from "./api";

const book: Book = {
  id: "book-1",
  filename: "book.epub",
  title: "测试图书",
  group_id: null,
  metadata: {
    authors: ["作者"],
    language: "ja",
    publisher: "",
    publicationDate: "",
    identifier: "",
    description: "",
    subjects: [],
    chapterCount: 1,
    fileSize: 1024,
    coverUrl: null,
  },
};

const settings: Settings = {
  provider: "deepseek",
  base_url: "https://api.deepseek.com",
  api_key: "",
  has_api_key: true,
  reasoning_style: "none",
  glow_mode: "none",
  source_lang: "auto",
  output_format: "epub",
  timeout: 600,
  max_retries: 4,
  strong: { model: "strong", thinking: true },
  cheap: { model: "cheap", thinking: true },
  fast: { model: "fast", thinking: false },
  mono: true,
  bilingual: false,
  bilingual_order: "target_first",
  polish: true,
  review: true,
  autofix_severe: true,
  book_understanding: true,
  consistency_qa: true,
  about_page: true,
};

const task = (status: Task["status"]): Task => ({
  id: "task-1",
  book_id: book.id,
  title: book.title,
  status,
  phase: "翻译",
  label: "处理中",
  fraction: 0.5,
  completed: 1,
  total: 2,
  outputs: status === "completed" ? ["translated.epub"] : [],
  updated_at: "2026-07-13T00:00:00Z",
});

const response = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  }));

type FetchHandler = (path: string, init?: RequestInit) => Promise<Response>;

function mockApi(tasks: Task[] = [], handler?: FetchHandler) {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (handler && (init?.method || !["/api/books", "/api/groups", "/api/tasks", "/api/settings"].includes(path))) {
      return handler(path, init);
    }
    if (path === "/api/books") return response([book]);
    if (path === "/api/groups") return response([]);
    if (path === "/api/tasks") return response(tasks);
    if (path === "/api/settings") {
      return init?.method === "PUT" && handler
        ? handler(path, init)
        : response(settings);
    }
    return response({ detail: "未处理请求" }, 500);
  }));
}

const openSettingsPage = async (page: "模型配置" | "WebUI 设置") => {
  fireEvent.click(await screen.findByRole("button", { name: "打开设置" }));
  fireEvent.click(screen.getByRole("button", { name: page }));
};

class MockEventSource {
  static instances: MockEventSource[] = [];
  onmessage: ((event: MessageEvent) => void) | null = null;
  close = vi.fn();

  constructor(public url: string) {
    MockEventSource.instances.push(this);
  }
}

beforeEach(() => {
  MockEventSource.instances = [];
  vi.stubGlobal("EventSource", MockEventSource);
  vi.stubGlobal("confirm", vi.fn(() => true));
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("settings", () => {
  it("disables glow switching while the full settings save is pending", async () => {
    let finishSave!: (value: Response) => void;
    const pendingSave = new Promise<Response>((resolve) => {
      finishSave = resolve;
    });
    mockApi([], (path) => path === "/api/settings" ? pendingSave : response({}));
    render(<App />);

    await openSettingsPage("WebUI 设置");
    fireEvent.click(screen.getByRole("button", { name: "保存设置" }));

    expect(screen.getByRole("button", { name: /切换卡片高光/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "取消" })).toBeDisabled();
    for (const close of screen.getAllByRole("button", { name: "关闭设置" })) {
      expect(close).toBeDisabled();
    }
    finishSave(new Response(JSON.stringify(settings), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
  });

  it("disables the full save while glow mode is being persisted", async () => {
    let finishSave!: (value: Response) => void;
    const pendingSave = new Promise<Response>((resolve) => {
      finishSave = resolve;
    });
    mockApi([], (path) => path === "/api/settings" ? pendingSave : response({}));
    render(<App />);

    await openSettingsPage("WebUI 设置");
    fireEvent.click(screen.getByRole("button", { name: /切换卡片高光/ }));

    expect(screen.getByRole("button", { name: "保存设置" })).toBeDisabled();
    finishSave(new Response(JSON.stringify(settings), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
  });

  it("sends the selected provider when testing the connection", async () => {
    let requestBody: Record<string, unknown> | undefined;
    mockApi([], async (path, init) => {
      if (path === "/api/settings/test-connection") {
        requestBody = JSON.parse(String(init?.body));
        return response({ ok: true, mode: "models", latency_ms: 1, checked_models: ["strong"] });
      }
      return response({});
    });
    render(<App />);

    await openSettingsPage("模型配置");
    fireEvent.change(screen.getByLabelText("服务类型"), { target: { value: "openai-compatible" } });
    expect(screen.getByLabelText("思考参数协议")).toHaveValue("none");
    expect(screen.getByText(/不转换服务商请求参数/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "检测连接" }));

    await waitFor(() => expect(requestBody?.provider).toBe("openai-compatible"));
  });

  it("clears the saved-key marker when switching providers", async () => {
    let savedBody: Settings | undefined;
    mockApi([], async (path, init) => {
      if (path === "/api/settings" && init?.method === "PUT") {
        savedBody = JSON.parse(String(init.body));
      }
      return response({});
    });
    render(<App />);

    await openSettingsPage("模型配置");
    expect(screen.getByLabelText("API Key")).toHaveAttribute(
      "placeholder",
      "已安全保存，留空保持不变",
    );
    fireEvent.change(screen.getByLabelText("服务类型"), { target: { value: "openai" } });
    expect(screen.getByLabelText("API Key")).toHaveAttribute("placeholder", "输入 API Key");
    fireEvent.click(screen.getByRole("button", { name: "保存设置" }));

    await waitFor(() => expect(savedBody?.provider).toBe("openai"));
    expect(savedBody?.api_key).toBe("");
    expect(savedBody?.has_api_key).toBe(false);
  });
});

describe("task controls", () => {
  it.each([
    ["running", "暂停", "暂停中…", "/api/tasks/task-1/stop", "暂停失败"],
    ["paused", "继续", "继续中…", "/api/tasks/task-1/resume", "继续失败"],
  ] as const)("keeps %s action local and reports failures", async (status, label, pending, path, error) => {
    let reject!: (value: Response) => void;
    const request = new Promise<Response>((resolve) => {
      reject = resolve;
    });
    mockApi([task(status)], (requestPath) => requestPath === path ? request : response({}));
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: label }));
    expect(screen.getByRole("button", { name: pending })).toBeDisabled();
    reject(new Response(JSON.stringify({ detail: error }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    }));

    expect(await screen.findByText(error)).toBeVisible();
    expect(screen.getByRole("button", { name: label })).toBeEnabled();
  });

  it("starts a fresh task from a completed task", async () => {
    const nextTask = { ...task("running"), id: "task-2", fraction: 0 };
    mockApi([task("completed")], (path) =>
      path === "/api/tasks" ? response(nextTask) : response({}),
    );
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "重新翻译" }));

    expect(await screen.findByRole("button", { name: "暂停" })).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(
      "/api/tasks",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("subscribes to every running task", async () => {
    mockApi([
      task("running"),
      { ...task("running"), id: "task-2", book_id: "book-2" },
    ]);
    render(<App />);

    await screen.findByText("测试图书");
    await waitFor(() => expect(MockEventSource.instances).toHaveLength(2));
    expect(MockEventSource.instances.map((source) => source.url)).toEqual([
      "/api/tasks/task-1/stream",
      "/api/tasks/task-2/stream",
    ]);
  });

  it("confirms lifecycle cleanup before deleting a book with a finished task", async () => {
    mockApi([task("completed")], (path) =>
      path === `/api/books/${book.id}` ? response({}) : response({}),
    );
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: `删除《${book.title}》` }));

    expect(confirm).toHaveBeenCalledWith(
      "确定删除这本书吗？关联的任务记录、状态和内部产物也会一并删除。",
    );
    expect(fetch).toHaveBeenCalledWith(
      `/api/books/${book.id}`,
      expect.objectContaining({ method: "DELETE" }),
    );
  });
});

describe("advanced workspace", () => {
  it("loads usage only after its tab is opened and distinguishes missing cache data", async () => {
    mockApi([task("completed")], (path) => {
      if (path === "/api/tasks/task-1/usage") {
        return response({
          workspace_ready: true,
          has_usage: true,
          cache_available: false,
          usage: {
            totals: { calls: 3, input_tokens: 1200, output_tokens: 345, total_tokens: 1545 },
            by_tier: { strong: { calls: 1, input_tokens: 800, output_tokens: 200, total_tokens: 1000 } },
            by_stage: {},
          },
        });
      }
      return response({});
    });
    render(<App />);

    await screen.findByText("测试图书");
    expect(fetch).not.toHaveBeenCalledWith("/api/tasks/task-1/usage", undefined);
    fireEvent.click(await screen.findByRole("button", { name: "用量" }));

    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/tasks/task-1/usage", undefined));
    expect(await screen.findByText("1,545")).toBeInTheDocument();
    expect(screen.getByText("无缓存数据")).toBeInTheDocument();
    expect(screen.getByText("按模型档位")).toBeInTheDocument();
  });

  it("keeps glossary data visible when a mutation fails", async () => {
    mockApi([task("completed")], (path, init) => {
      if (path === "/api/tasks/task-1/glossary/terms" && !init?.method) {
        return response({
          workspace_ready: true,
          editable: true,
          terms: [{
            source: "猫",
            target: "cat",
            reading: "ねこ",
            type: "term",
            gender: "",
            note: "",
            confidence: "high",
            locked: false,
            status: "active",
          }],
        });
      }
      if (path === "/api/tasks/task-1/glossary/conflicts") return response({ conflicts: [] });
      if (path.endsWith("/lock")) return response({ detail: "锁定失败" }, 500);
      return response({});
    });
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "术语" }));
    expect(await screen.findByText("cat")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "锁定术语「猫」" }));

    expect(await screen.findByText("锁定失败")).toBeVisible();
    expect(screen.getByText("cat")).toBeVisible();
  });

  it("saves only the two editable analysis fields", async () => {
    let saved: Record<string, unknown> | undefined;
    const analysis = {
      genre: "小说",
      tone: "克制",
      narration: "第三人称",
      pacing: "舒缓",
      dialogue_style: "自然",
      rhetoric: "简洁",
      characters: [],
      style_guide: "旧指南",
      book_synopsis: "旧概要",
      chapter_summaries: [],
    };
    mockApi([task("completed")], (path, init) => {
      if (path === "/api/tasks/task-1/analysis" && init?.method === "PATCH") {
        saved = JSON.parse(String(init.body));
        return response({ workspace_ready: true, editable: true, analysis: { ...analysis, ...saved } });
      }
      if (path === "/api/tasks/task-1/analysis") {
        return response({ workspace_ready: true, editable: true, analysis });
      }
      return response({});
    });
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "风格概要" }));
    const guide = await screen.findByLabelText("风格指南");
    fireEvent.change(guide, { target: { value: "新指南" } });
    fireEvent.click(screen.getByRole("button", { name: "保存概要" }));

    await waitFor(() => expect(saved).toEqual({
      style_guide: "新指南",
      book_synopsis: "旧概要",
    }));
  });

  it("shows a preparing state when analysis is not ready", async () => {
    mockApi([task("running")], (path) =>
      path === "/api/tasks/task-1/analysis"
        ? response({ workspace_ready: false, editable: false, analysis: null })
        : response({}),
    );
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "风格概要" }));

    expect(await screen.findByText(/翻译工作区正在准备/)).toBeInTheDocument();
  });

  it("shows an empty analysis state when the workspace exists", async () => {
    mockApi([task("completed")], (path) =>
      path === "/api/tasks/task-1/analysis"
        ? response({ workspace_ready: true, editable: false, analysis: null })
        : response({}),
    );
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "风格概要" }));

    expect(await screen.findByText("尚未生成风格概要。")).toBeInTheDocument();
  });

  it("preserves dirty analysis drafts across background phase refreshes", async () => {
    let reads = 0;
    const analysis = (style_guide: string, book_synopsis: string) => ({
      genre: "小说",
      tone: "克制",
      narration: "第三人称",
      pacing: "舒缓",
      dialogue_style: "自然",
      rhetoric: "简洁",
      characters: [],
      style_guide,
      book_synopsis,
      chapter_summaries: [],
    });
    mockApi([{ ...task("running"), phase_code: "prescan" }], (path) => {
      if (path === "/api/tasks/task-1/analysis") {
        reads += 1;
        return response({
          workspace_ready: true,
          editable: true,
          analysis: reads === 1
            ? analysis("服务端旧指南", "服务端旧概要")
            : analysis("服务端新指南", "服务端新概要"),
        });
      }
      return response({});
    });
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "风格概要" }));
    const guide = await screen.findByLabelText("风格指南");
    fireEvent.change(guide, { target: { value: "用户未保存草稿" } });
    await act(async () => {
      MockEventSource.instances[0].onmessage?.(new MessageEvent("message", {
        data: JSON.stringify({
          type: "snapshot",
          task: { ...task("running"), phase_code: "translate", workspace_ready: true },
        }),
      }));
    });

    await waitFor(() => expect(reads).toBeGreaterThan(1));
    expect(screen.getByLabelText("风格指南")).toHaveValue("用户未保存草稿");
    expect(screen.getByLabelText("全书概要")).toHaveValue("服务端新概要");
  });

  it("retains a review draft after save failure", async () => {
    mockApi([task("completed")], (path, init) => {
      if (path === "/api/tasks/task-1/chapters") {
        return response({
          workspace_ready: true,
          editable: true,
          chapters: [{ index: 0, title: "第一章", title_translated: "第一章", status: "done", segment_count: 1, review_complete: false }],
        });
      }
      if (path === "/api/tasks/task-1/chapters/0") {
        return response({
          workspace_ready: true,
          editable: true,
          chapter: {
            index: 0,
            title: "第一章",
            title_translated: "第一章",
            status: "done",
            review_complete: false,
            source_digest: "",
            segments: [{ index: 0, source: "原文", target: "旧译文", kind: "text" }],
            review_issues: [],
            backtranslation_issues: [],
          },
        });
      }
      if (path.endsWith("/segments/0") && init?.method === "PATCH") {
        return response({ detail: "保存失败" }, 500);
      }
      return response({});
    });
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "审校" }));
    const translation = await screen.findByDisplayValue("旧译文");
    fireEvent.change(translation, { target: { value: "尚未保存的新译文" } });
    fireEvent.click(screen.getByRole("button", { name: "保存本段" }));

    expect(await screen.findByText("保存失败")).toBeVisible();
    expect(screen.getByDisplayValue("尚未保存的新译文")).toHaveValue("尚未保存的新译文");
  });

  it("confirms before discarding a dirty review draft", async () => {
    vi.mocked(confirm).mockReturnValue(false);
    mockApi([task("completed")], (path) => {
      if (path === "/api/tasks/task-1/chapters") {
        return response({
          workspace_ready: true,
          editable: true,
          chapters: [
            { index: 0, title: "第一章", title_translated: "第一章", status: "done", segment_count: 1, review_complete: false },
            { index: 1, title: "第二章", title_translated: "第二章", status: "done", segment_count: 1, review_complete: false },
          ],
        });
      }
      if (path === "/api/tasks/task-1/chapters/0") {
        return response({
          workspace_ready: true,
          editable: true,
          chapter: {
            index: 0, title: "第一章", title_translated: "第一章", status: "done",
            review_complete: false, source_digest: "",
            segments: [{ index: 0, source: "原文", target: "旧译文", kind: "text" }],
            review_issues: [], backtranslation_issues: [],
          },
        });
      }
      return response({});
    });
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "审校" }));
    fireEvent.change(await screen.findByDisplayValue("旧译文"), { target: { value: "未保存" } });
    fireEvent.change(screen.getByLabelText("审校章节"), { target: { value: "1" } });

    expect(confirm).toHaveBeenCalledWith("当前章节有尚未保存的修改，确定放弃并切换章节吗？");
    expect(fetch).not.toHaveBeenCalledWith("/api/tasks/task-1/chapters/1", undefined);
    expect(screen.getByLabelText("审校章节")).toHaveValue("0");
  });

  it("keeps the latest chapter response when requests finish out of order", async () => {
    let finishOne!: (value: Response) => void;
    let finishTwo!: (value: Response) => void;
    const one = new Promise<Response>((resolve) => { finishOne = resolve; });
    const two = new Promise<Response>((resolve) => { finishTwo = resolve; });
    const detail = (index: number, title: string) => ({
      workspace_ready: true,
      editable: true,
      chapter: {
        index, title, title_translated: title, status: "done",
        review_complete: false, source_digest: "",
        segments: [{ index: 0, source: `${title}原文`, target: `${title}译文`, kind: "text" }],
        review_issues: [], backtranslation_issues: [],
      },
    });
    mockApi([task("completed")], (path) => {
      if (path === "/api/tasks/task-1/chapters") {
        return response({
          workspace_ready: true,
          editable: true,
          chapters: [0, 1, 2].map((index) => ({
            index, title: `第${index + 1}章`, title_translated: `第${index + 1}章`,
            status: "done", segment_count: 1, review_complete: false,
          })),
        });
      }
      if (path === "/api/tasks/task-1/chapters/0") return response(detail(0, "第一章"));
      if (path === "/api/tasks/task-1/chapters/1") return one;
      if (path === "/api/tasks/task-1/chapters/2") return two;
      return response({});
    });
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "审校" }));
    const selector = await screen.findByLabelText("审校章节");
    fireEvent.change(selector, { target: { value: "1" } });
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/tasks/task-1/chapters/1", undefined));
    fireEvent.change(selector, { target: { value: "2" } });
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/tasks/task-1/chapters/2", undefined));
    finishTwo(await response(detail(2, "第三章")));
    expect(await screen.findByDisplayValue("第三章译文")).toBeInTheDocument();
    finishOne(await response(detail(1, "第二章")));
    await waitFor(() => expect(screen.queryByDisplayValue("第二章译文")).not.toBeInTheDocument());
    expect(screen.getByDisplayValue("第三章译文")).toBeInTheDocument();
  });

  it("creates one export with the existing underscore order values", async () => {
    let saved: Record<string, unknown> | undefined;
    const completed = { ...task("completed"), completed: 2, total: 2 };
    mockApi([completed], (path, init) => {
      if (path === "/api/tasks/task-1/exports" && init?.method === "POST") {
        saved = JSON.parse(String(init.body));
        return response({
          id: "export-1",
          format: "epub",
          mode: "bilingual",
          bilingual_order: "source_first",
          about_page: true,
          status: "completed",
          size: 12,
          created_at: "2026-07-13T00:00:00Z",
          error: null,
          filename: "translated.epub",
          download_url: "/download",
          historical: false,
        });
      }
      if (path === "/api/tasks/task-1/exports") {
        return response({ workspace_ready: true, outputs_stale: false, exports: [] });
      }
      return response({});
    });
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "导出" }));
    await screen.findByText("重新导出");
    fireEvent.change(screen.getByLabelText("内容"), { target: { value: "bilingual" } });
    fireEvent.change(screen.getByLabelText("双语顺序"), { target: { value: "source_first" } });
    fireEvent.click(screen.getByRole("button", { name: "创建导出" }));

    await waitFor(() => expect(saved).toEqual({
      format: "epub",
      mono: false,
      bilingual: true,
      bilingual_order: "source_first",
      about_page: true,
    }));
  });

  it("stops event polling when the events tab is left", async () => {
    const interval = vi.spyOn(window, "setInterval");
    const clear = vi.spyOn(window, "clearInterval");
    mockApi([task("running")], (path) => {
      if (path === "/api/tasks/task-1/events?limit=200") {
        return response({
          workspace_ready: true,
          types: ["translate"],
          events: [{ type: "translate", message: "章节完成", timestamp: "2026-07-13T00:00:00Z" }],
        });
      }
      return response({});
    });
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "事件" }));
    expect(await screen.findByText("章节完成")).toBeInTheDocument();
    expect(interval).toHaveBeenCalledWith(expect.any(Function), 5000);
    const eventTimerIndex = interval.mock.calls.findIndex((call) => call[1] === 5000);
    const timer = interval.mock.results[eventTimerIndex]?.value;
    fireEvent.click(screen.getByRole("button", { name: "概览" }));

    expect(clear).toHaveBeenCalledWith(timer);
  });

  it("polls usage while running and stops after leaving the tab", async () => {
    const interval = vi.spyOn(window, "setInterval");
    const clear = vi.spyOn(window, "clearInterval");
    mockApi([task("running")], (path) =>
      path === "/api/tasks/task-1/usage"
        ? response({
          workspace_ready: true,
          has_usage: false,
          cache_available: false,
          usage: {
            totals: { calls: 0, input_tokens: 0, output_tokens: 0, total_tokens: 0 },
            by_tier: {},
            by_stage: {},
          },
        })
        : response({}),
    );
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "用量" }));
    expect(await screen.findByText("尚无 Token 用量记录。")).toBeInTheDocument();
    expect(interval).toHaveBeenCalledWith(expect.any(Function), 5000);
    const usageTimerIndex = interval.mock.calls.findIndex((call) => call[1] === 5000);
    const timer = interval.mock.results[usageTimerIndex]?.value;
    fireEvent.click(screen.getByRole("button", { name: "概览" }));

    expect(clear).toHaveBeenCalledWith(timer);
  });
});
