import Foundation
import Observation
import UserNotifications

@MainActor @Observable
final class TranslationManager {
    private var processes: [UUID: Process] = [:]
    private var decoders: [UUID: JSONLineDecoder] = [:]
    private var diagnostics: [UUID: String] = [:]
    private var monitors: [UUID: Task<Void, Never>] = [:]
    private unowned let library: LibraryStore

    init(library: LibraryStore) {
        self.library = library
        for book in library.books { refreshProgress(for: book.id) }
    }

    func start(_ book: BookRecord) {
        guard processes[book.id] == nil else { return }
        guard !library.settings.apiKey.isEmpty else { fail(book, "请先在设置中填写 API Key"); return }
        guard let source = library.resolveSource(for: book), source.startAccessingSecurityScopedResource() else { fail(book, "无法访问原始图书，请重新导入"); return }
        guard let outputDirectory = outputDirectory(), outputDirectory.startAccessingSecurityScopedResource() else { source.stopAccessingSecurityScopedResource(); fail(book, "请先选择输出目录"); return }
        guard let managed = library.settings.managedPythonPath, let runtime = PythonDetector().probe(managed), runtime.isUsable else { source.stopAccessingSecurityScopedResource(); outputDirectory.stopAccessingSecurityScopedResource(); fail(book, "文译专用 Python 环境尚未就绪，请先在设置中安装依赖"); return }

        do {
            let config = try writeConfig(for: book)
            let output = outputDirectory.appendingPathComponent("\(book.title).zh.epub")
            let process = Process(); let stdout = Pipe(); let stderr = Pipe()
            process.executableURL = URL(fileURLWithPath: runtime.path)
            process.arguments = ["-m", "trans_novel.app_worker", "--task-id", book.id.uuidString, "--input", source.path, "--output", output.path, "--state-dir", book.stateDirectory, "--config", config.path]
            var environment = ProcessInfo.processInfo.environment
            environment["DEEPSEEK_API_KEY"] = library.settings.apiKey
            environment["PYTHONPATH"] = Bundle.main.resourceURL?.path
            process.environment = environment; process.standardOutput = stdout; process.standardError = stderr
            decoders[book.id] = JSONLineDecoder()
            stdout.fileHandleForReading.readabilityHandler = { [weak self] handle in
                let data = handle.availableData
                guard !data.isEmpty else { return }
                Task { @MainActor in
                    guard var decoder = self?.decoders[book.id] else { return }
                    let lines = decoder.append(data)
                    self?.decoders[book.id] = decoder
                    for line in lines { self?.handle(line, bookID: book.id) }
                }
            }
            stderr.fileHandleForReading.readabilityHandler = { [weak self] handle in
                let data = handle.availableData
                guard !data.isEmpty else { return }
                let text = String(decoding: data, as: UTF8.self)
                Task { @MainActor in
                    let key = self?.library.settings.apiKey ?? ""
                    let redacted = key.isEmpty ? text : text.replacingOccurrences(of: key, with: "[REDACTED]")
                    self?.diagnostics[book.id, default: ""] += redacted
                }
            }
            process.terminationHandler = { [weak self] process in Task { @MainActor in
                source.stopAccessingSecurityScopedResource(); outputDirectory.stopAccessingSecurityScopedResource()
                self?.processes.removeValue(forKey: book.id)
                self?.decoders.removeValue(forKey: book.id)
                self?.monitors.removeValue(forKey: book.id)?.cancel()
                if process.terminationStatus != 0, var current = self?.library.books.first(where: { $0.id == book.id }), current.status == .running {
                    RuntimeClock.recoverInterruptedRun(&current)
                    current.status = .failed
                    current.errorMessage = self?.diagnostics.removeValue(forKey: book.id)?.trimmingCharacters(in: .whitespacesAndNewlines).suffix(2000).description ?? "Python worker 异常退出"
                    self?.library.update(current)
                }
            }}
            try process.run(); processes[book.id] = process
            var current = book; current.status = .running; current.errorMessage = nil; current.currentRunStartedAt = Date(); current.lastRunHeartbeatAt = current.currentRunStartedAt; library.update(current)
            startProgressMonitor(for: book.id)
        } catch { source.stopAccessingSecurityScopedResource(); outputDirectory.stopAccessingSecurityScopedResource(); fail(book, error.localizedDescription) }
    }

    func stop(_ book: BookRecord) {
        guard let process = processes[book.id] else { return }
        var current = book; current.status = .paused; RuntimeClock.settle(&current); library.update(current)
        monitors.removeValue(forKey: book.id)?.cancel()
        process.terminate()
        Task { try? await Task.sleep(for: .seconds(5)); if process.isRunning { kill(process.processIdentifier, SIGKILL) } }
    }

    private func handle(_ data: Data, bookID: UUID) {
        guard let event = try? JSONDecoder().decode(WorkerEvent.self, from: data), event.protocolVersion == 1,
              var book = library.books.first(where: { $0.id == bookID }) else { return }
        switch event.type {
        case "phase": book.phase = event.label ?? event.phase ?? ""
        case "progress":
            book.progress = event.fraction
            book.progressLabel = event.label ?? ""
            if let completed = event.completed { book.completedSegments = completed }
            if let total = event.total { book.totalSegments = total }
            book.phase = ProgressPhaseResolver.phase(current: book.phase, label: book.progressLabel, completedSegments: book.completedSegments)
        case "completed": monitors.removeValue(forKey: bookID)?.cancel(); RuntimeClock.settle(&book); book.status = .completed; book.progress = 1; book.outputs = event.outputs ?? []; notify(book, success: true)
        case "failed": monitors.removeValue(forKey: bookID)?.cancel(); RuntimeClock.settle(&book); book.status = .failed; book.errorMessage = event.message; notify(book, success: false)
        default: break
        }
        library.update(book)
    }

    private func startProgressMonitor(for bookID: UUID) {
        monitors[bookID]?.cancel()
        monitors[bookID] = Task { [weak self] in
            while !Task.isCancelled {
                guard let self, let book = library.books.first(where: { $0.id == bookID }), book.status == .running else { return }
                refreshProgress(for: bookID)
                if var current = library.books.first(where: { $0.id == bookID }) {
                    current.lastRunHeartbeatAt = Date()
                    library.update(current)
                }
                try? await Task.sleep(for: .seconds(2))
            }
        }
    }

    private func refreshProgress(for bookID: UUID) {
        guard var book = library.books.first(where: { $0.id == bookID }),
              let snapshot = ProgressSnapshotReader().read(stateDirectory: book.stateDirectory) else { return }
        book.completedSegments = snapshot.completedSegments
        book.totalSegments = snapshot.totalSegments
        book.completedChapters = snapshot.completedChapters
        book.totalChapters = snapshot.totalChapters
        book.progress = snapshot.fraction
        book.phase = ProgressPhaseResolver.phase(current: book.phase, label: book.progressLabel, completedSegments: snapshot.completedSegments)
        library.update(book)
    }

    private func outputDirectory() -> URL? {
        guard let data = library.settings.outputDirectoryBookmark else { return nil }
        var stale = false; return try? URL(resolvingBookmarkData: data, options: [.withSecurityScope], bookmarkDataIsStale: &stale)
    }

    private func writeConfig(for book: BookRecord) throws -> URL {
        let s = library.settings; let o = s.options
        let text = """
        language: { source: auto, target: zh }
        llm:
          provider: deepseek
          base_url: \(s.baseURL)
          api_key_env: DEEPSEEK_API_KEY
          timeout: \(s.timeout)
          max_retries: \(s.maxRetries)
          tiers:
            strong: { model: \(s.strong.model), thinking: \(s.strong.thinking), reasoning_effort: \(s.strong.reasoningEffort) }
            cheap: { model: \(s.cheap.model), thinking: \(s.cheap.thinking), reasoning_effort: \(s.cheap.reasoningEffort) }
            fast: { model: \(s.fast.model), thinking: \(s.fast.thinking), reasoning_effort: \(s.fast.reasoningEffort) }
        pipeline: { review: \(o.review), autofix_severe: \(o.autofixSevere), polish: \(o.polish), book_understanding: \(o.bookUnderstanding), consistency_qa: \(o.consistencyQA) }
        output: { mono: \(o.mono), bilingual: \(o.bilingual), bilingual_order: \(o.bilingualOrder) }
        paths: { state_dir: \(book.stateDirectory) }
        """
        let url = URL(fileURLWithPath: book.stateDirectory).appendingPathComponent("task-config.yaml")
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try text.write(to: url, atomically: true, encoding: .utf8); return url
    }

    private func fail(_ book: BookRecord, _ message: String) { var current = book; current.status = .failed; current.errorMessage = message; library.update(current) }
    private func notify(_ book: BookRecord, success: Bool) { let content = UNMutableNotificationContent(); content.title = success ? "翻译完成" : "翻译失败"; content.body = book.title; UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: book.id.uuidString, content: content, trigger: nil)) }
}
