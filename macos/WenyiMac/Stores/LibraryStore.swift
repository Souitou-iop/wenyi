import AppKit
import Foundation
import Observation

@MainActor @Observable
final class LibraryStore {
    var books: [BookRecord] = []
    var selection: UUID?
    var settings: AppSettings
    var runtimes: [PythonRuntime] = []
    var settingsError: String?
    let pythonEnvironment = PythonEnvironmentManager()
    private let settingsStore = SecureSettingsStore()
    private let libraryURL: URL

    init() {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("文译", isDirectory: true)
        libraryURL = base.appendingPathComponent("library.json")
        settings = (try? settingsStore.load()) ?? AppSettings()
        if let managed = settings.managedPythonPath,
           FileManager.default.isExecutableFile(atPath: managed),
           let runtime = PythonDetector().probe(managed), runtime.isUsable {
            pythonEnvironment.state = .ready(managed)
            runtimes = [runtime]
        }
        loadBooks()
        for index in books.indices {
            if books[index].status == .running {
                books[index].status = .paused
                RuntimeClock.recoverInterruptedRun(&books[index])
            }
            if !books[index].runtimeHistoryInitialized {
                books[index].accumulatedRunSeconds = RuntimeHistoryReader().read(stateDirectory: books[index].stateDirectory) ?? 0
                books[index].runtimeHistoryInitialized = true
            }
        }
        saveBooks()
        for book in books where book.format == "epub" && book.metadata.chapterCount == 0 {
            refreshMetadata(for: book.id)
        }
    }

    var selectedBook: BookRecord? {
        guard let selection else { return nil }
        return books.first { $0.id == selection }
    }

    var runningCount: Int { books.filter { $0.status == .running }.count }

    func importBooks() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = true
        panel.allowedContentTypes = [.epub, .plainText, .init(filenameExtension: "fb2")].compactMap { $0 }
        guard panel.runModal() == .OK else { return }
        for url in panel.urls { add(url) }
    }

    func add(_ url: URL) {
        let canonical = url.resolvingSymlinksInPath().path
        guard !books.contains(where: { $0.sourcePathHint == canonical }) else { return }
        guard let bookmark = try? url.bookmarkData(options: [.withSecurityScope]) else { return }
        let id = UUID()
        let state = applicationSupport().appendingPathComponent("State/\(id.uuidString)").path
        books.append(BookRecord(
            id: id,
            title: url.deletingPathExtension().lastPathComponent,
            sourceBookmark: bookmark,
            sourcePathHint: canonical,
            format: url.pathExtension.lowercased(),
            stateDirectory: state
        ))
        selection = id
        saveBooks()
        refreshMetadata(for: id)
    }

    func resolveSource(for book: BookRecord) -> URL? {
        var stale = false
        guard let url = try? URL(resolvingBookmarkData: book.sourceBookmark, options: [.withSecurityScope], bookmarkDataIsStale: &stale), !stale else {
            if var current = books.first(where: { $0.id == book.id }) { current.status = .needsRelocation; update(current) }
            return nil
        }
        return url
    }

    func relocate(_ book: BookRecord) {
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.epub, .plainText, .init(filenameExtension: "fb2")].compactMap { $0 }
        guard panel.runModal() == .OK, let url = panel.url, let bookmark = try? url.bookmarkData(options: [.withSecurityScope]) else { return }
        var current = book; current.sourceBookmark = bookmark; current.sourcePathHint = url.path; current.status = .paused; update(current)
        refreshMetadata(for: book.id)
    }

    func update(_ book: BookRecord) {
        guard let index = books.firstIndex(where: { $0.id == book.id }) else { return }
        books[index] = book
        saveBooks()
    }

    func remove(_ book: BookRecord) {
        if let cover = book.metadata.coverPath { try? FileManager.default.removeItem(atPath: cover) }
        try? FileManager.default.removeItem(atPath: book.stateDirectory)
        books.removeAll { $0.id == book.id }
        if selection == book.id { selection = books.first?.id }
        saveBooks()
    }

    func refreshMetadata(for id: UUID) {
        guard let book = books.first(where: { $0.id == id }), let url = resolveSource(for: book) else { return }
        let python = settings.pythonPath.isEmpty ? "/usr/bin/python3" : settings.pythonPath
        Task {
            do {
                let inspected = try await BookInspector().inspect(url: url, bookID: id, python: python)
                guard var current = books.first(where: { $0.id == id }) else { return }
                current.title = inspected.title
                current.metadata = BookMetadata(authors: inspected.authors, language: inspected.language, publisher: inspected.publisher, publicationDate: inspected.publicationDate, identifier: inspected.identifier, bookDescription: inspected.description, subjects: inspected.subjects, chapterCount: inspected.chapterCount, fileSize: inspected.fileSize, coverPath: inspected.coverPath)
                update(current)
            } catch {
                guard var current = books.first(where: { $0.id == id }) else { return }
                current.errorMessage = "读取图书信息失败：\(error.localizedDescription)"; update(current)
            }
        }
    }

    func saveSettings() {
        do { try settingsStore.save(settings); settingsError = nil }
        catch { settingsError = error.localizedDescription }
    }

    func installPythonEnvironment(force: Bool = false) {
        let base = settings.pythonPath
        Task { if let managed = await pythonEnvironment.ensure(basePython: base, force: force) { settings.managedPythonPath = managed; saveSettings() } }
    }

    func configurePythonAutomatically() {
        Task {
            pythonEnvironment.state = .installing("正在检测 Python…")
            let values = await PythonDetector().detect()
            runtimes = values
            guard let best = values.first(where: { PythonRuntime.versionIsSupported($0.version) }) else {
                pythonEnvironment.state = .failed("未找到 Python 3.10 或更高版本")
                return
            }
            settings.pythonPath = best.path
            settings.managedPythonPath = nil
            saveSettings()
            if let managed = await pythonEnvironment.ensure(basePython: best.path) {
                settings.managedPythonPath = managed
                saveSettings()
            }
        }
    }

    private func loadBooks() {
        guard let data = try? Data(contentsOf: libraryURL), let value = try? JSONDecoder().decode([BookRecord].self, from: data) else { return }
        books = value
        selection = books.first?.id
    }

    private func saveBooks() {
        let directory = libraryURL.deletingLastPathComponent()
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        guard let data = try? JSONEncoder().encode(books) else { return }
        try? data.write(to: libraryURL, options: .atomic)
    }

    private func applicationSupport() -> URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("文译", isDirectory: true)
    }
}
