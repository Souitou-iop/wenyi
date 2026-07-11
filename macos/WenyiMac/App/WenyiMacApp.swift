import AppKit
import SwiftUI
import UserNotifications

@main
struct WenyiMacApp: App {
    @State private var library: LibraryStore
    @State private var manager: TranslationManager

    init() {
        let store = LibraryStore()
        _library = State(initialValue: store)
        _manager = State(initialValue: TranslationManager(library: store))
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }

    var body: some Scene {
        WindowGroup {
            ContentView(library: library, manager: manager)
                .frame(minWidth: 880, minHeight: 580)
        }
        .commands { AppCommands(library: library, manager: manager) }

        Settings { SettingsView(library: library) }
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
