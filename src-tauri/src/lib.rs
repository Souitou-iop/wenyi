pub mod commands;
pub mod config;
pub mod inspector;
pub mod power;
pub mod python_env;
pub mod tray;
pub mod types;
pub mod worker;

use std::path::PathBuf;
use std::sync::Arc;

use crate::commands::*;
use crate::power::PowerManager;
use crate::tray::TrayManager;
use crate::worker::TaskManager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let _ = env_logger::try_init();

    // 解析当前工作区根目录
    let workspace_root = std::env::current_dir()
        .unwrap_or_else(|_| PathBuf::from("."))
        .canonicalize()
        .unwrap_or_else(|_| PathBuf::from("."));

    let cache_dir = dirs::cache_dir()
        .unwrap_or_else(|| PathBuf::from("./state/cache"))
        .join("wenyi");
    let _ = std::fs::create_dir_all(&cache_dir);

    let task_manager = Arc::new(TaskManager::new());
    let power_manager = Arc::new(PowerManager::new());

    let app_state = AppState {
        workspace_root,
        task_manager,
        power_manager,
        cache_dir,
    };

    tauri::Builder::default()
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_process::init())
        .manage(app_state)
        .setup(|app| {
            let handle = app.handle();
            let _ = TrayManager::setup_tray(handle);
            log::info!("Wenyi desktop application initialized successfully");
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            detect_python_environments,
            validate_python_executable,
            load_app_config,
            save_app_config,
            inspect_book_file,
            start_translation,
            stop_translation,
            get_current_task,
            set_prevent_sleep,
            get_prevent_sleep_status,
            send_system_notification,
            open_path_in_file_manager,
        ])
        .run(tauri::generate_context!())
        .expect("error while running wenyi tauri application");
}
