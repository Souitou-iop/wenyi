use std::fs;
use std::path::{Path, PathBuf};
use crate::types::FullAppConfig;

pub struct ConfigManager;

impl ConfigManager {
    /// 定位 config.yaml 配置文件路径
    pub fn get_config_path(workspace_root: Option<&Path>) -> PathBuf {
        if let Some(ws) = workspace_root {
            let ws_cfg = ws.join("config.yaml");
            if ws_cfg.exists() {
                return ws_cfg;
            }
        }

        // 检查当前执行工作区
        let cur = PathBuf::from("config.yaml");
        if cur.exists() {
            return cur;
        }

        // 检查上一级（针对 src-tauri 运行时）
        let parent_cfg = PathBuf::from("../config.yaml");
        if parent_cfg.exists() {
            return parent_cfg;
        }

        // 否则存放在系统 AppConfig 目录
        if let Some(config_dir) = dirs::config_dir() {
            let app_dir = config_dir.join("wenyi");
            let _ = fs::create_dir_all(&app_dir);
            return app_dir.join("config.yaml");
        }

        PathBuf::from("config.yaml")
    }

    /// 读取配置
    pub fn load_config(workspace_root: Option<&Path>) -> FullAppConfig {
        let path = Self::get_config_path(workspace_root);
        if path.exists() {
            if let Ok(content) = fs::read_to_string(&path) {
                if let Ok(cfg) = serde_yaml::from_str::<FullAppConfig>(&content) {
                    return cfg;
                }
            }
        }
        FullAppConfig::default()
    }

    /// 保存配置
    pub fn save_config(cfg: &FullAppConfig, workspace_root: Option<&Path>) -> Result<PathBuf, String> {
        let path = Self::get_config_path(workspace_root);
        if let Some(parent) = path.parent() {
            let _ = fs::create_dir_all(parent);
        }

        let yaml_str = serde_yaml::to_string(cfg)
            .map_err(|e| format!("序列化配置失败: {}", e))?;

        let tmp_path = path.with_extension("yaml.tmp");
        fs::write(&tmp_path, yaml_str)
            .map_err(|e| format!("写入临时配置文件失败: {}", e))?;

        fs::rename(&tmp_path, &path)
            .map_err(|e| format!("重命名保存配置文件失败: {}", e))?;

        Ok(path)
    }
}
