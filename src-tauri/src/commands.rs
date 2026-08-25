use std::path::{Path, PathBuf};
use std::sync::Arc;
use tauri::{AppHandle, State};
use tauri_plugin_notification::NotificationExt;

use crate::config::ConfigManager;
use crate::inspector::BookInspector;
use crate::power::PowerManager;
use crate::python_env::PythonEnvManager;
use crate::types::{BookMetadata, FullAppConfig, PythonEnvInfo, StartTaskPayload, TaskSnapshot};
use crate::worker::TaskManager;

pub struct AppState {
    pub workspace_root: PathBuf,
    pub task_manager: Arc<TaskManager>,
    pub power_manager: Arc<PowerManager>,
    pub cache_dir: PathBuf,
}

#[tauri::command]
pub async fn detect_python_environments(
    custom_path: Option<String>,
    state: State<'_, AppState>,
) -> Result<Vec<PythonEnvInfo>, String> {
    Ok(PythonEnvManager::detect_all(custom_path.as_deref(), Some(&state.workspace_root)).await)
}

#[tauri::command]
pub async fn validate_python_executable(
    path: String,
    state: State<'_, AppState>,
) -> Result<PythonEnvInfo, String> {
    Ok(PythonEnvManager::validate_executable("custom", &path, Some(&state.workspace_root)).await)
}

#[tauri::command]
pub async fn load_app_config(state: State<'_, AppState>) -> Result<FullAppConfig, String> {
    Ok(ConfigManager::load_config(Some(&state.workspace_root)))
}

#[tauri::command]
pub async fn save_app_config(
    config: FullAppConfig,
    state: State<'_, AppState>,
) -> Result<(), String> {
    // 联动休眠设置
    let _ = state.power_manager.set_prevent_sleep(config.preferences.prevent_sleep).await;
    ConfigManager::save_config(&config, Some(&state.workspace_root)).map(|_| ())
}

#[tauri::command]
pub async fn inspect_book_file(
    path: String,
    state: State<'_, AppState>,
) -> Result<BookMetadata, String> {
    let covers_dir = state.cache_dir.join("covers");
    BookInspector::inspect_file(&path, Some(&covers_dir))
}

#[tauri::command]
pub async fn start_translation(
    payload: StartTaskPayload,
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<TaskSnapshot, String> {
    // 1. 读取当前配置中的 Python 路径，若无则自动探测
    let cfg = ConfigManager::load_config(Some(&state.workspace_root));
    let py_path = if let Some(custom) = &cfg.preferences.custom_python_path {
        if !custom.trim().is_empty() && Path::new(custom).exists() {
            custom.clone()
        } else {
            PythonEnvManager::find_best_python(None, Some(&state.workspace_root))
                .await
                .ok_or_else(|| "未找到可用的 Python 环境，请先在设置中指定 Python 路径".to_string())?
        }
    } else {
        PythonEnvManager::find_best_python(None, Some(&state.workspace_root))
            .await
            .ok_or_else(|| "未找到可用的 Python 环境，请先在设置中指定 Python 路径".to_string())?
    };

    // 2. 如果开启了防休眠，自动申请休眠锁
    if cfg.preferences.prevent_sleep {
        let _ = state.power_manager.set_prevent_sleep(true).await;
    }

    // 3. 启动任务
    state
        .task_manager
        .start_task(app, py_path, payload, Some(state.workspace_root.clone()))
        .await
}

#[tauri::command]
pub async fn stop_translation(
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<(), String> {
    state.task_manager.stop_task(app).await
}

#[tauri::command]
pub async fn get_current_task(state: State<'_, AppState>) -> Result<Option<TaskSnapshot>, String> {
    Ok(state.task_manager.get_current_task().await)
}

#[tauri::command]
pub async fn set_prevent_sleep(
    enabled: bool,
    state: State<'_, AppState>,
) -> Result<bool, String> {
    state.power_manager.set_prevent_sleep(enabled).await
}

#[tauri::command]
pub async fn get_prevent_sleep_status(state: State<'_, AppState>) -> Result<bool, String> {
    Ok(state.power_manager.is_active())
}

#[tauri::command]
pub async fn send_system_notification(
    title: String,
    body: String,
    app: AppHandle,
) -> Result<(), String> {
    app.notification()
        .builder()
        .title(title)
        .body(body)
        .show()
        .map_err(|e| format!("发送通知失败: {}", e))
}

#[tauri::command]
pub async fn open_path_in_file_manager(path: String) -> Result<(), String> {
    let target = Path::new(&path);
    if !target.exists() {
        return Err("目标文件或目录不存在".to_string());
    }

    let folder_to_open = if target.is_file() {
        target.parent().unwrap_or(target)
    } else {
        target
    };

    open::that(folder_to_open).map_err(|e| format!("打开目录失败: {}", e))
}
