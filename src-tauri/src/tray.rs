use tauri::{
    menu::{Menu, MenuItem, PredefinedMenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Manager,
};

pub struct TrayManager;

impl TrayManager {
    pub fn setup_tray(app: &AppHandle) -> Result<(), Box<dyn std::error::Error>> {
        let toggle_item = MenuItem::with_id(app, "toggle_window", "显示/隐藏主窗口", true, None::<&str>)?;
        let separator = PredefinedMenuItem::separator(app)?;
        let quit_item = MenuItem::with_id(app, "quit", "退出文译", true, None::<&str>)?;

        let menu = Menu::with_items(app, &[
            &toggle_item,
            &separator,
            &quit_item,
        ])?;

        let tray_builder = TrayIconBuilder::with_id("main-tray")
            .tooltip("文译 - AI 书籍长文本翻译")
            .menu(&menu)
            .show_menu_on_left_click(false)
            .on_menu_event(|app, event| {
                match event.id.as_ref() {
                    "toggle_window" => {
                        if let Some(window) = app.get_webview_window("main") {
                            if let Ok(is_visible) = window.is_visible() {
                                if is_visible {
                                    let _ = window.hide();
                                } else {
                                    let _ = window.show();
                                    let _ = window.set_focus();
                                }
                            }
                        }
                    }
                    "quit" => {
                        app.exit(0);
                    }
                    _ => {}
                }
            })
            .on_tray_icon_event(|tray, event| {
                if let TrayIconEvent::Click {
                    button: MouseButton::Left,
                    button_state: MouseButtonState::Up,
                    ..
                } = event
                {
                    let app = tray.app_handle();
                    if let Some(window) = app.get_webview_window("main") {
                        let _ = window.show();
                        let _ = window.set_focus();
                    }
                }
            });

        // 绑定图标
        if let Some(icon) = app.default_window_icon().cloned() {
            let _ = tray_builder.icon(icon).build(app)?;
        } else {
            let _ = tray_builder.build(app)?;
        }

        Ok(())
    }
}
