use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use tokio::sync::Mutex;

#[derive(Clone)]
pub struct PowerManager {
    is_preventing: Arc<AtomicBool>,
    #[cfg(target_os = "macos")]
    caffeinate_child: Arc<Mutex<Option<tokio::process::Child>>>,
}

impl PowerManager {
    pub fn new() -> Self {
        Self {
            is_preventing: Arc::new(AtomicBool::new(false)),
            #[cfg(target_os = "macos")]
            caffeinate_child: Arc::new(Mutex::new(None)),
        }
    }

    pub fn is_active(&self) -> bool {
        self.is_preventing.load(Ordering::SeqCst)
    }

    pub async fn set_prevent_sleep(&self, enable: bool) -> Result<bool, String> {
        if enable {
            self.acquire_assertion().await?;
        } else {
            self.release_assertion().await?;
        }
        Ok(self.is_active())
    }

    async fn acquire_assertion(&self) -> Result<(), String> {
        if self.is_preventing.load(Ordering::SeqCst) {
            return Ok(());
        }

        #[cfg(target_os = "macos")]
        {
            let mut child_guard = self.caffeinate_child.lock().await;
            if child_guard.is_none() {
                match tokio::process::Command::new("caffeinate")
                    .args(["-d", "-i", "-m", "-u"])
                    .stdout(std::process::Stdio::null())
                    .stderr(std::process::Stdio::null())
                    .spawn()
                {
                    Ok(child) => {
                        *child_guard = Some(child);
                        log::info!("macOS caffeinate sleep assertion acquired");
                    }
                    Err(e) => {
                        log::warn!("Failed to spawn caffeinate on macOS: {}", e);
                    }
                }
            }
        }

        #[cfg(target_os = "windows")]
        {
            // Windows SetThreadExecutionState
            // ES_CONTINUOUS (0x80000000) | ES_SYSTEM_REQUIRED (0x00000001) | ES_AWAYMODE_REQUIRED (0x00000040)
            unsafe {
                #[link(name = "kernel32")]
                extern "system" {
                    fn SetThreadExecutionState(esFlags: u32) -> u32;
                }
                const ES_CONTINUOUS: u32 = 0x80000000;
                const ES_SYSTEM_REQUIRED: u32 = 0x00000001;
                const ES_AWAYMODE_REQUIRED: u32 = 0x00000040;
                SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED);
                log::info!("Windows SetThreadExecutionState sleep assertion acquired");
            }
        }

        self.is_preventing.store(true, Ordering::SeqCst);
        Ok(())
    }

    async fn release_assertion(&self) -> Result<(), String> {
        if !self.is_preventing.load(Ordering::SeqCst) {
            return Ok(());
        }

        #[cfg(target_os = "macos")]
        {
            let mut child_guard = self.caffeinate_child.lock().await;
            if let Some(mut child) = child_guard.take() {
                let _ = child.kill().await;
                log::info!("macOS caffeinate sleep assertion released");
            }
        }

        #[cfg(target_os = "windows")]
        {
            unsafe {
                #[link(name = "kernel32")]
                extern "system" {
                    fn SetThreadExecutionState(esFlags: u32) -> u32;
                }
                const ES_CONTINUOUS: u32 = 0x80000000;
                SetThreadExecutionState(ES_CONTINUOUS);
                log::info!("Windows SetThreadExecutionState sleep assertion reset");
            }
        }

        self.is_preventing.store(false, Ordering::SeqCst);
        Ok(())
    }
}
