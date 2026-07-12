import AppKit
import SwiftUI
import UserNotifications

@main
struct WenyiMacApp: App {
    @State private var library: LibraryStore
    @State private var manager: TranslationManager

    init() {
        NSWindow.allowsAutomaticWindowTabbing = false
        let store = LibraryStore()
        _library = State(initialValue: store)
        _manager = State(initialValue: TranslationManager(library: store))
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }

    var body: some Scene {
        Window("文译", id: "main") {
            ContentView(library: library, manager: manager)
                .frame(minWidth: 880, minHeight: 580)
                .background {
                    WindowTabbingConfigurator()
                        .frame(width: 0, height: 0)
                }
        }
        .commands { AppCommands(library: library, manager: manager) }

        Settings { SettingsView(library: library) }
    }
}

private struct WindowTabbingConfigurator: NSViewRepresentable {
    func makeNSView(context: Context) -> NSView {
        WindowProbeView()
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        (nsView as? WindowProbeView)?.disableTabbing()
    }
}

private final class WindowProbeView: NSView {
    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        disableTabbing()
    }

    func disableTabbing() {
        window?.tabbingMode = .disallowed
    }
}

struct AppCommands: Commands {
    let library: LibraryStore
    let manager: TranslationManager
    var body: some Commands {
        CommandGroup(after: .newItem) {
            Button("导入图书…") { library.importBooks() }.keyboardShortcut("o")
        }
        CommandMenu("翻译") {
            Button("开始或继续") { if let book = library.selectedBook { manager.start(book) } }.keyboardShortcut(.return)
            Button("停止") { if let book = library.selectedBook { manager.stop(book) } }.keyboardShortcut(".")
        }
    }
}
