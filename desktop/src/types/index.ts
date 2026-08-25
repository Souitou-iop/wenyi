export interface PythonEnvInfo {
  id: string;
  name: string;
  path: string;
  version: string;
  isValid: boolean;
  hasWenyi: boolean;
  kind: "venv" | "uv" | "system" | "custom" | string;
  statusMessage: string;
}

export interface BookMetadata {
  id: string;
  path: string;
  filename: string;
  format: string;
  title: string;
  authors: string[];
  language: string;
  description: string;
  chapterCount: number;
  fileSize: number;
  coverPath?: string | null;
}

export type TaskStatus = "idle" | "running" | "paused" | "completed" | "failed" | "cancelled";

export interface TaskSnapshot {
  taskId: string;
  bookPath: string;
  bookTitle: string;
  outputPath: string;
  stateDir: string;
  status: TaskStatus;
  currentPhase: string;
  phaseLabel: string;
  progressFraction: number;
  completedUnits: number;
  totalUnits: number;
  recentLogs: string[];
  outputs: string[];
  errorMessage?: string | null;
  startedAt?: string | null;
  updatedAt: string;
}

export interface LlmConfig {
  api_base: string;
  api_key: string;
  model: string;
  temperature: number;
  timeout: number;
  max_retries: number;
  rpm?: number | null;
  tpm?: number | null;
}

export interface OutputConfig {
  mono: boolean;
  bilingual: boolean;
  dir: string;
}

export interface AppPreferences {
  custom_python_path?: string | null;
  prevent_sleep: boolean;
  enable_notifications: boolean;
  default_output_dir?: string | null;
}

export interface FullAppConfig {
  llm: LlmConfig;
  output: OutputConfig;
  preferences: AppPreferences;
}

export interface StartTaskPayload {
  inputPath: string;
  outputPath?: string | null;
  stateDir?: string | null;
  outFormat?: string | null;
  customConfigPath?: string | null;
}
