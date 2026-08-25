use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PythonEnvInfo {
    pub id: String,
    pub name: String,
    pub path: String,
    pub version: String,
    pub is_valid: bool,
    pub has_wenyi: bool,
    pub kind: String, // "venv", "uv", "system", "custom"
    pub status_message: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BookMetadata {
    pub id: String,
    pub path: String,
    pub filename: String,
    pub format: String,
    pub title: String,
    pub authors: Vec<String>,
    pub language: String,
    pub description: String,
    pub chapter_count: usize,
    pub file_size: u64,
    pub cover_path: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkerSummary {
    #[serde(default)]
    pub cue_count: Option<usize>,
    #[serde(default)]
    pub translated: Option<usize>,
    #[serde(default)]
    pub chapters_total: Option<usize>,
    #[serde(default)]
    pub chapters_translated: Option<usize>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct WorkerEvent {
    pub protocol_version: Option<u32>,
    pub task_id: Option<String>,
    #[serde(rename = "type")]
    pub event_type: String,
    #[serde(default)]
    pub timestamp: Option<String>,
    #[serde(default)]
    pub phase: Option<String>,
    #[serde(default)]
    pub label: Option<String>,
    #[serde(default)]
    pub completed: Option<usize>,
    #[serde(default)]
    pub total: Option<usize>,
    #[serde(default)]
    pub fraction: Option<f64>,
    #[serde(default)]
    pub outputs: Option<Vec<String>>,
    #[serde(default)]
    pub summary: Option<serde_json::Value>,
    #[serde(default)]
    pub state_directory: Option<String>,
    #[serde(default)]
    pub code: Option<String>,
    #[serde(default)]
    pub message: Option<String>,
    #[serde(default)]
    pub worker_version: Option<String>,
    #[serde(default)]
    pub python_version: Option<String>,
    #[serde(default)]
    pub executable: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub enum TaskStatus {
    Idle,
    Running,
    Paused,
    Completed,
    Failed,
    Cancelled,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TaskSnapshot {
    pub task_id: String,
    pub book_path: String,
    pub book_title: String,
    pub output_path: String,
    pub state_dir: String,
    pub status: TaskStatus,
    pub current_phase: String,
    pub phase_label: String,
    pub progress_fraction: f64,
    pub completed_units: usize,
    pub total_units: usize,
    pub recent_logs: Vec<String>,
    pub outputs: Vec<String>,
    pub error_message: Option<String>,
    pub started_at: Option<String>,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StartTaskPayload {
    pub input_path: String,
    pub output_path: Option<String>,
    pub state_dir: Option<String>,
    pub out_format: Option<String>,
    pub custom_config_path: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LlmConfig {
    #[serde(default = "default_api_base")]
    pub api_base: String,
    #[serde(default)]
    pub api_key: String,
    #[serde(default = "default_model")]
    pub model: String,
    #[serde(default = "default_temperature")]
    pub temperature: f64,
    #[serde(default = "default_timeout")]
    pub timeout: u64,
    #[serde(default = "default_max_retries")]
    pub max_retries: u32,
    #[serde(default)]
    pub rpm: Option<u32>,
    #[serde(default)]
    pub tpm: Option<u32>,
}

fn default_api_base() -> String {
    "https://api.openai.com/v1".to_string()
}
fn default_model() -> String {
    "gpt-4o-mini".to_string()
}
fn default_temperature() -> f64 {
    0.3
}
fn default_timeout() -> u64 {
    120
}
fn default_max_retries() -> u32 {
    3
}

impl Default for LlmConfig {
    fn default() -> Self {
        Self {
            api_base: default_api_base(),
            api_key: String::new(),
            model: default_model(),
            temperature: default_temperature(),
            timeout: default_timeout(),
            max_retries: default_max_retries(),
            rpm: None,
            tpm: None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OutputConfig {
    #[serde(default = "default_true")]
    pub mono: bool,
    #[serde(default = "default_true")]
    pub bilingual: bool,
    #[serde(default = "default_output_dir")]
    pub dir: String,
}

fn default_true() -> bool {
    true
}
fn default_output_dir() -> String {
    "./output".to_string()
}

impl Default for OutputConfig {
    fn default() -> Self {
        Self {
            mono: true,
            bilingual: true,
            dir: default_output_dir(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct AppPreferences {
    #[serde(default)]
    pub custom_python_path: Option<String>,
    #[serde(default = "default_true")]
    pub prevent_sleep: bool,
    #[serde(default = "default_true")]
    pub enable_notifications: bool,
    #[serde(default)]
    pub default_output_dir: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct FullAppConfig {
    #[serde(default)]
    pub llm: LlmConfig,
    #[serde(default)]
    pub output: OutputConfig,
    #[serde(default)]
    pub preferences: AppPreferences,
}
