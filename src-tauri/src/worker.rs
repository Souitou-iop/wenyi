use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::Arc;
use tauri::{AppHandle, Emitter};
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::sync::Mutex;

use crate::types::{StartTaskPayload, TaskSnapshot, TaskStatus, WorkerEvent};

pub struct TaskManager {
    inner: Arc<Mutex<TaskManagerInner>>,
}

struct TaskManagerInner {
    current_task: Option<TaskSnapshot>,
    child_handle: Option<tokio::process::Child>,
}

impl TaskManager {
    pub fn new() -> Self {
        Self {
            inner: Arc::new(Mutex::new(TaskManagerInner {
                current_task: None,
                child_handle: None,
            })),
        }
    }

    pub async fn get_current_task(&self) -> Option<TaskSnapshot> {
        let guard = self.inner.lock().await;
        guard.current_task.clone()
    }

    pub async fn start_task(
        &self,
        app: AppHandle,
        python_exe: String,
        payload: StartTaskPayload,
        workspace_root: Option<PathBuf>,
    ) -> Result<TaskSnapshot, String> {
        let mut guard = self.inner.lock().await;

        if let Some(task) = &guard.current_task {
            if task.status == TaskStatus::Running {
                return Err("当前已有翻译任务正在执行，请先等待完成或停止当前任务".to_string());
            }
        }

        let input_path = Path::new(&payload.input_path);
        if !input_path.exists() {
            return Err(format!("输入文件不存在: {}", payload.input_path));
        }

        let task_id = format!("task_{}", uuid::Uuid::new_v4().simple());
        let book_title = input_path.file_stem().unwrap_or_default().to_string_lossy().to_string();
        let ext = input_path.extension().unwrap_or_default().to_string_lossy().to_string();

        let output_path = payload.output_path.unwrap_or_else(|| {
            let parent = input_path.parent().unwrap_or_else(|| Path::new("."));
            parent.join(format!("{}.zh.{}", book_title, ext)).to_string_lossy().to_string()
        });

        let state_dir = payload.state_dir.unwrap_or_else(|| {
            if let Some(ws) = &workspace_root {
                ws.join("state").join(&task_id).to_string_lossy().to_string()
            } else {
                format!("./state/{}", task_id)
            }
        });

        let config_path = payload.custom_config_path.unwrap_or_else(|| {
            if let Some(ws) = &workspace_root {
                ws.join("config.yaml").to_string_lossy().to_string()
            } else {
                "config.yaml".to_string()
            }
        });

        let out_format = payload.out_format.unwrap_or_else(|| {
            if ext == "srt" { "srt".to_string() } else { "epub".to_string() }
        });

        let now_str = chrono::Local::now().to_rfc3339();
        let initial_snapshot = TaskSnapshot {
            task_id: task_id.clone(),
            book_path: payload.input_path.clone(),
            book_title: book_title.clone(),
            output_path: output_path.clone(),
            state_dir: state_dir.clone(),
            status: TaskStatus::Running,
            current_phase: "init".to_string(),
            phase_label: "正在初始化翻译引擎...".to_string(),
            progress_fraction: 0.0,
            completed_units: 0,
            total_units: 0,
            recent_logs: vec!["启动文译 Worker 进程...".to_string()],
            outputs: vec![],
            error_message: None,
            started_at: Some(now_str.clone()),
            updated_at: now_str,
        };

        // 启动 Python 子进程
        let mut cmd = tokio::process::Command::new(&python_exe);
        cmd.args([
            "-m",
            "trans_novel.app_worker",
            "--task-id",
            &task_id,
            "--input",
            &payload.input_path,
            "--output",
            &output_path,
            "--state-dir",
            &state_dir,
            "--config",
            &config_path,
            "--format",
            &out_format,
        ]);

        if let Some(ws) = &workspace_root {
            cmd.current_dir(ws);
        }

        cmd.env("PYTHONUNBUFFERED", "1");
        cmd.env("PYTHONIOENCODING", "utf-8");
        cmd.stdout(Stdio::piped());
        cmd.stderr(Stdio::piped());

        let mut child = cmd.spawn().map_err(|e| format!("启动 Python 进程失败 ({}): {}", python_exe, e))?;

        let stdout = child.stdout.take().ok_or_else(|| "无法获取子进程 stdout".to_string())?;
        let stderr = child.stderr.take().ok_or_else(|| "无法获取子进程 stderr".to_string())?;

        guard.current_task = Some(initial_snapshot.clone());
        guard.child_handle = Some(child);

        // 广播初始状态
        let _ = app.emit("task://status", &initial_snapshot);

        // 启动后台事件监听线程
        let inner_clone = Arc::clone(&self.inner);
        let app_clone = app.clone();

        tokio::spawn(async move {
            let mut stdout_reader = BufReader::new(stdout).lines();
            let mut stderr_reader = BufReader::new(stderr).lines();

            // 监听 stderr 错误日志
            let app_err = app_clone.clone();
            let inner_err = Arc::clone(&inner_clone);
            tokio::spawn(async move {
                while let Ok(Some(line)) = stderr_reader.next_line().await {
                    log::warn!("[worker stderr] {}", line);
                    let mut guard = inner_err.lock().await;
                    if let Some(task) = &mut guard.current_task {
                        task.recent_logs.push(format!("[Err] {}", line));
                        if task.recent_logs.len() > 100 {
                            task.recent_logs.remove(0);
                        }
                        let _ = app_err.emit("task://status", &*task);
                    }
                }
            });

            while let Ok(Some(line)) = stdout_reader.next_line().await {
                let trimmed = line.trim();
                if trimmed.is_empty() {
                    continue;
                }

                if let Ok(event) = serde_json::from_str::<WorkerEvent>(trimmed) {
                    let mut guard = inner_clone.lock().await;
                    if let Some(task) = &mut guard.current_task {
                        task.updated_at = chrono::Local::now().to_rfc3339();

                        match event.event_type.as_str() {
                            "ready" => {
                                task.recent_logs.push("翻译引擎已就绪".to_string());
                            }
                            "phase" => {
                                if let Some(p) = &event.phase {
                                    task.current_phase = p.clone();
                                }
                                if let Some(l) = &event.label {
                                    task.phase_label = l.clone();
                                    task.recent_logs.push(format!("进入阶段: {}", l));
                                }
                            }
                            "progress" => {
                                if let Some(c) = event.completed {
                                    task.completed_units = c;
                                }
                                if let Some(t) = event.total {
                                    task.total_units = t;
                                }
                                if let Some(f) = event.fraction {
                                    task.progress_fraction = f;
                                }
                                if let Some(l) = &event.label {
                                    task.phase_label = l.clone();
                                }
                            }
                            "completed" => {
                                task.status = TaskStatus::Completed;
                                task.progress_fraction = 1.0;
                                task.phase_label = "翻译已全部完成".to_string();
                                if let Some(outs) = event.outputs.clone() {
                                    task.outputs = outs;
                                }
                                task.recent_logs.push("🎉 翻译任务执行完成！".to_string());
                            }
                            "failed" => {
                                if task.status != TaskStatus::Cancelled {
                                    task.status = TaskStatus::Failed;
                                    task.error_message = event.message.clone();
                                    task.phase_label = format!("失败: {}", event.message.as_deref().unwrap_or("未知异常"));
                                    task.recent_logs.push(format!("❌ 任务失败: {:?}", event.message));
                                }
                            }
                            _ => {}
                        }

                        if task.recent_logs.len() > 100 {
                            task.recent_logs.remove(0);
                        }

                        let _ = app_clone.emit("worker://event", &event);
                        let _ = app_clone.emit("task://status", &*task);
                    }
                } else {
                    log::info!("[worker raw stdout] {}", trimmed);
                }
            }

            // 进程退出处理
            let mut guard = inner_clone.lock().await;
            if let Some(mut child) = guard.child_handle.take() {
                let status = child.wait().await;
                if let Some(task) = &mut guard.current_task {
                    if task.status == TaskStatus::Running {
                        match status {
                            Ok(s) if s.success() => {
                                task.status = TaskStatus::Completed;
                                task.progress_fraction = 1.0;
                            }
                            _ => {
                                task.status = TaskStatus::Failed;
                                task.phase_label = "翻译进程意外终止".to_string();
                            }
                        }
                        let _ = app_clone.emit("task://status", &*task);
                    }
                }
            }
        });

        Ok(initial_snapshot)
    }

    pub async fn stop_task(&self, app: AppHandle) -> Result<(), String> {
        let mut guard = self.inner.lock().await;
        #[allow(unused_mut)]
        if let Some(mut child) = guard.child_handle.take() {
            #[cfg(unix)]
            {
                if let Some(pid) = child.id() {
                    unsafe {
                        libc::kill(pid as i32, libc::SIGINT);
                    }
                }
            }
            #[cfg(not(unix))]
            {
                let _ = child.kill().await;
            }

            if let Some(task) = &mut guard.current_task {
                task.status = TaskStatus::Cancelled;
                task.phase_label = "任务已由用户手动停止".to_string();
                task.recent_logs.push("已发送停止信号，进程正在安全退出...".to_string());
                let _ = app.emit("task://status", &*task);
            }
            Ok(())
        } else {
            Err("当前没有正在运行的任务".to_string())
        }
    }
}
