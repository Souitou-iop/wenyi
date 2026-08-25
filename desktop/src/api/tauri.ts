import { invoke } from "@tauri-apps/api/core";
import { listen, UnlistenFn } from "@tauri-apps/api/event";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import {
  BookMetadata,
  FullAppConfig,
  PythonEnvInfo,
  StartTaskPayload,
  TaskSnapshot,
} from "../types";

export const isTauri = (): boolean => {
  return typeof window !== "undefined" && Boolean((window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__);
};

export async function detectPythonEnvironments(customPath?: string): Promise<PythonEnvInfo[]> {
  if (!isTauri()) {
    return [
      {
        id: "mock-venv",
        name: "本地虚拟环境 (.venv)",
        path: "/Volumes/SanDisk/Projects/wenyi/.venv/bin/python",
        version: "3.12.14",
        isValid: true,
        hasWenyi: true,
        kind: "venv",
        statusMessage: "环境就绪 (Web 模拟模式)",
      },
    ];
  }
  return await invoke<PythonEnvInfo[]>("detect_python_environments", { customPath });
}

export async function validatePythonExecutable(path: string): Promise<PythonEnvInfo> {
  if (!isTauri()) {
    return {
      id: "mock-custom",
      name: "指定 Python",
      path,
      version: "3.12.x",
      isValid: true,
      hasWenyi: true,
      kind: "custom",
      statusMessage: "校验通过",
    };
  }
  return await invoke<PythonEnvInfo>("validate_python_executable", { path });
}

export async function loadAppConfig(): Promise<FullAppConfig> {
  if (!isTauri()) {
    return {
      llm: {
        api_base: "https://api.openai.com/v1",
        api_key: "",
        model: "gpt-4o-mini",
        temperature: 0.3,
        timeout: 120,
        max_retries: 3,
        rpm: null,
        tpm: null,
      },
      output: {
        mono: true,
        bilingual: true,
        dir: "./output",
      },
      preferences: {
        custom_python_path: null,
        prevent_sleep: true,
        enable_notifications: true,
        default_output_dir: "./output",
      },
    };
  }
  return await invoke<FullAppConfig>("load_app_config");
}

export async function saveAppConfig(config: FullAppConfig): Promise<void> {
  if (!isTauri()) return;
  await invoke("save_app_config", { config });
}

export async function inspectBookFile(path: string): Promise<BookMetadata> {
  if (!isTauri()) {
    const filename = path.split("/").pop() || "sample.epub";
    return {
      id: "mock-book-1",
      path,
      filename,
      format: "epub",
      title: filename.replace(/\.[^/.]+$/, ""),
      authors: ["George R.R. Martin"],
      language: "en",
      description: "A Game of Thrones is the first novel in A Song of Ice and Fire.",
      chapterCount: 73,
      fileSize: 2841200,
      coverPath: null,
    };
  }
  return await invoke<BookMetadata>("inspect_book_file", { path });
}

export async function startTranslation(payload: StartTaskPayload): Promise<TaskSnapshot> {
  if (!isTauri()) {
    return {
      taskId: "mock-task-1",
      bookPath: payload.inputPath,
      bookTitle: "Mock Book",
      outputPath: "./output/mock.zh.epub",
      stateDir: "./state/mock-task-1",
      status: "running",
      currentPhase: "translating",
      phaseLabel: "正在翻译第 1 章节...",
      progressFraction: 0.15,
      completedUnits: 1,
      totalUnits: 10,
      recentLogs: ["[Mock] 启动翻译引擎", "[Mock] 正在处理第 1 章节"],
      outputs: [],
      errorMessage: null,
      startedAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
  }
  return await invoke<TaskSnapshot>("start_translation", { payload });
}

export async function stopTranslation(): Promise<void> {
  if (!isTauri()) return;
  await invoke("stop_translation");
}

export async function getCurrentTask(): Promise<TaskSnapshot | null> {
  if (!isTauri()) return null;
  return await invoke<TaskSnapshot | null>("get_current_task");
}

export async function setPreventSleep(enabled: boolean): Promise<boolean> {
  if (!isTauri()) return enabled;
  return await invoke<boolean>("set_prevent_sleep", { enabled });
}

export async function getPreventSleepStatus(): Promise<boolean> {
  if (!isTauri()) return true;
  return await invoke<boolean>("get_prevent_sleep_status");
}

export async function openPathInFileManager(path: string): Promise<void> {
  if (!isTauri()) return;
  await invoke("open_path_in_file_manager", { path });
}

export async function pickBookFile(): Promise<string | null> {
  if (!isTauri()) return null;
  const selected = await openDialog({
    multiple: false,
    filters: [
      {
        name: "书籍与字幕",
        extensions: ["epub", "docx", "srt", "txt", "md", "markdown", "fb2"],
      },
    ],
  });
  if (Array.isArray(selected)) return selected[0] || null;
  return selected;
}

export async function pickPythonBinary(): Promise<string | null> {
  if (!isTauri()) return null;
  const selected = await openDialog({
    multiple: false,
  });
  if (Array.isArray(selected)) return selected[0] || null;
  return selected;
}

export async function listenToTaskStatus(callback: (snapshot: TaskSnapshot) => void): Promise<UnlistenFn> {
  if (!isTauri()) return () => {};
  return await listen<TaskSnapshot>("task://status", (event) => {
    callback(event.payload);
  });
}
