use std::path::{Path, PathBuf};
use std::process::Stdio;
use tokio::process::Command;
use tokio::time::{timeout, Duration};

use crate::types::PythonEnvInfo;

pub struct PythonEnvManager;

impl PythonEnvManager {
    /// 寻找内置的 Sidecar 可执行文件 (wenyi-worker)
    pub fn find_sidecar_executable(workspace_root: Option<&Path>) -> Option<PathBuf> {
        let exe_name = if cfg!(windows) { "wenyi-worker.exe" } else { "wenyi-worker" };

        let mut candidate_paths = Vec::new();

        // 1. 本地构建目录
        if let Some(ws) = workspace_root {
            candidate_paths.push(ws.join("dist").join("binaries").join(exe_name));
            candidate_paths.push(ws.join("src-tauri").join("binaries").join(exe_name));
        }

        // 2. 当前二进制所在目录及其上级 resources
        if let Ok(cur_exe) = std::env::current_exe() {
            if let Some(parent) = cur_exe.parent() {
                candidate_paths.push(parent.join(exe_name));
                candidate_paths.push(parent.join("resources").join(exe_name));
                candidate_paths.push(parent.join("../Resources").join(exe_name));
            }
        }

        for path in candidate_paths {
            if path.exists() {
                return Some(path);
            }
        }

        None
    }

    /// 搜集系统中可能存在的 Python 环境路径列表
    pub fn discover_candidates(custom_path: Option<&str>, workspace_root: Option<&Path>) -> Vec<(String, String)> {
        let mut candidates = Vec::new();

        // 0. 内置 Sidecar 二进制（最高优先级）
        if let Some(sidecar) = Self::find_sidecar_executable(workspace_root) {
            candidates.push(("sidecar".to_string(), sidecar.to_string_lossy().to_string()));
        }

        // 1. 用户自定义路径
        if let Some(custom) = custom_path {
            if !custom.trim().is_empty() {
                candidates.push(("custom".to_string(), custom.trim().to_string()));
            }
        }

        // 2. 工作区本地 .venv
        let roots = [
            workspace_root.map(|p| p.to_path_buf()),
            std::env::current_dir().ok(),
            std::env::current_exe().ok().and_then(|p| p.parent().map(|d| d.to_path_buf())),
        ];

        for root_opt in roots.into_iter().flatten() {
            #[cfg(unix)]
            let venv_py = root_opt.join(".venv").join("bin").join("python");
            #[cfg(windows)]
            let venv_py = root_opt.join(".venv").join("Scripts").join("python.exe");

            if venv_py.exists() {
                candidates.push(("venv".to_string(), venv_py.to_string_lossy().to_string()));
            }

            // 检查上一级目录的 .venv（若从 src-tauri 启动）
            #[cfg(unix)]
            let parent_venv_py = root_opt.parent().map(|p| p.join(".venv").join("bin").join("python"));
            #[cfg(windows)]
            let parent_venv_py = root_opt.parent().map(|p| p.join(".venv").join("Scripts").join("python.exe"));

            if let Some(p) = parent_venv_py {
                if p.exists() {
                    candidates.push(("venv".to_string(), p.to_string_lossy().to_string()));
                }
            }
        }

        // 3. 环境变量 PATH 中的 uv / python3 / python
        if let Ok(uv_path) = which::which("uv") {
            candidates.push(("uv".to_string(), uv_path.to_string_lossy().to_string()));
        }
        if let Ok(py3) = which::which("python3") {
            candidates.push(("system".to_string(), py3.to_string_lossy().to_string()));
        }
        if let Ok(py) = which::which("python") {
            candidates.push(("system".to_string(), py.to_string_lossy().to_string()));
        }

        // 4. 平台常见路径
        #[cfg(target_os = "macos")]
        {
            let mac_paths = [
                "/opt/homebrew/bin/python3",
                "/usr/local/bin/python3",
                "/usr/bin/python3",
            ];
            for p in mac_paths {
                if Path::new(p).exists() {
                    candidates.push(("system".to_string(), p.to_string()));
                }
            }
        }

        #[cfg(target_os = "windows")]
        {
            if let Ok(local_app_data) = std::env::var("LOCALAPPDATA") {
                let py_base = PathBuf::from(local_app_data).join("Programs").join("Python");
                if py_base.exists() {
                    if let Ok(entries) = std::fs::read_dir(py_base) {
                        for entry in entries.flatten() {
                            let py_exe = entry.path().join("python.exe");
                            if py_exe.exists() {
                                candidates.push(("system".to_string(), py_exe.to_string_lossy().to_string()));
                            }
                        }
                    }
                }
            }
        }

        // 去重
        let mut seen = std::collections::HashSet::new();
        let mut unique = Vec::new();
        for (kind, path) in candidates {
            let normalized = Path::new(&path).canonicalize().unwrap_or_else(|_| PathBuf::from(&path));
            let key = normalized.to_string_lossy().to_string();
            if seen.insert(key) {
                unique.push((kind, path));
            }
        }

        unique
    }

    /// 验证单个可执行文件并探查 trans_novel 模块
    pub async fn validate_executable(kind: &str, path: &str, workspace_root: Option<&Path>) -> PythonEnvInfo {
        let name = match kind {
            "sidecar" => "内置独立核心引擎 (Sidecar)",
            "custom" => "用户指定 Python",
            "venv" => "项目虚拟环境 (.venv)",
            "uv" => "uv 运行时",
            _ => "系统 Python",
        }
        .to_string();

        let path_obj = Path::new(path);
        if !path_obj.exists() {
            return PythonEnvInfo {
                id: uuid::Uuid::new_v4().to_string(),
                name,
                path: path.to_string(),
                version: "未知".to_string(),
                is_valid: false,
                has_wenyi: false,
                kind: kind.to_string(),
                status_message: "路径不存在".to_string(),
            };
        }

        // 如果是 Sidecar 单二进制程序，直接运行 --help 测试
        if kind == "sidecar" || path.ends_with("wenyi-worker") || path.ends_with("wenyi-worker.exe") {
            let mut cmd = Command::new(path);
            cmd.arg("--help");
            cmd.stdout(Stdio::piped());
            cmd.stderr(Stdio::piped());

            let res = timeout(Duration::from_secs(5), cmd.output()).await;
            return match res {
                Ok(Ok(out)) if out.status.success() => PythonEnvInfo {
                    id: uuid::Uuid::new_v4().to_string(),
                    name,
                    path: path.to_string(),
                    version: "内置 3.12".to_string(),
                    is_valid: true,
                    has_wenyi: true,
                    kind: "sidecar".to_string(),
                    status_message: "开箱即用，已内置完整 Python 运行时与所有依赖".to_string(),
                },
                _ => PythonEnvInfo {
                    id: uuid::Uuid::new_v4().to_string(),
                    name,
                    path: path.to_string(),
                    version: "异常".to_string(),
                    is_valid: false,
                    has_wenyi: false,
                    kind: "sidecar".to_string(),
                    status_message: "内置引擎校验失败".to_string(),
                },
            };
        }

        // 尝试导入 trans_novel 并打印 Python 版本与实际解释器
        let py_script = "import sys\ntry:\n    import trans_novel\n    has_wenyi = True\nexcept Exception as e:\n    has_wenyi = False\nprint(f'{sys.version.split()[0]}|{has_wenyi}')";

        let mut cmd = Command::new(path);
        cmd.arg("-c").arg(py_script);
        if let Some(ws) = workspace_root {
            cmd.current_dir(ws);
        }
        cmd.stdout(Stdio::piped());
        cmd.stderr(Stdio::piped());

        let res = timeout(Duration::from_secs(5), cmd.output()).await;

        match res {
            Ok(Ok(output)) if output.status.success() => {
                let stdout_str = String::from_utf8_lossy(&output.stdout).trim().to_string();
                let parts: Vec<&str> = stdout_str.split('|').collect();
                let version = parts.first().unwrap_or(&"3.x").trim().to_string();
                let has_wenyi = parts.get(1).map(|v| v.trim() == "True").unwrap_or(false);

                let status_message = if has_wenyi {
                    "环境就绪，包含文译 (trans_novel) 核心模块".to_string()
                } else {
                    "Python 可用，但未检测到 trans_novel 核心模块（请先执行 uv sync）".to_string()
                };

                PythonEnvInfo {
                    id: uuid::Uuid::new_v4().to_string(),
                    name,
                    path: path.to_string(),
                    version,
                    is_valid: true,
                    has_wenyi,
                    kind: kind.to_string(),
                    status_message,
                }
            }
            Ok(Ok(output)) => {
                let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
                PythonEnvInfo {
                    id: uuid::Uuid::new_v4().to_string(),
                    name,
                    path: path.to_string(),
                    version: "错误".to_string(),
                    is_valid: false,
                    has_wenyi: false,
                    kind: kind.to_string(),
                    status_message: if stderr.is_empty() { "进程退出码非零".to_string() } else { stderr },
                }
            }
            Ok(Err(e)) => PythonEnvInfo {
                id: uuid::Uuid::new_v4().to_string(),
                name,
                path: path.to_string(),
                version: "失败".to_string(),
                is_valid: false,
                has_wenyi: false,
                kind: kind.to_string(),
                status_message: format!("执行失败: {}", e),
            },
            Err(_) => PythonEnvInfo {
                id: uuid::Uuid::new_v4().to_string(),
                name,
                path: path.to_string(),
                version: "超时".to_string(),
                is_valid: false,
                has_wenyi: false,
                kind: kind.to_string(),
                status_message: "执行探测脚本超时 (5s)".to_string(),
            },
        }
    }

    /// 全量检测所有可用环境
    pub async fn detect_all(custom_path: Option<&str>, workspace_root: Option<&Path>) -> Vec<PythonEnvInfo> {
        let candidates = Self::discover_candidates(custom_path, workspace_root);
        let mut results = Vec::new();

        for (kind, path) in candidates {
            let info = Self::validate_executable(&kind, &path, workspace_root).await;
            results.push(info);
        }

        // 排序：内置 Sidecar > 具备文译模块的环境 > 有效环境
        results.sort_by(|a, b| {
            let a_is_sidecar = a.kind == "sidecar";
            let b_is_sidecar = b.kind == "sidecar";

            b_is_sidecar
                .cmp(&a_is_sidecar)
                .then_with(|| b.has_wenyi.cmp(&a.has_wenyi))
                .then_with(|| b.is_valid.cmp(&a.is_valid))
                .then_with(|| a.kind.cmp(&b.kind))
        });

        results
    }

    /// 选出最佳默认可用 Python 路径
    pub async fn find_best_python(custom_path: Option<&str>, workspace_root: Option<&Path>) -> Option<String> {
        let envs = Self::detect_all(custom_path, workspace_root).await;
        envs.into_iter().find(|e| e.is_valid && e.has_wenyi).map(|e| e.path)
    }
}
