import AppKit
import Foundation
import Testing
@testable import WenyiMac

struct SecureSettingsStoreTests {
    @Test func savesAndLoadsSettingsWithPrivatePermissions() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let store = SecureSettingsStore(directory: root)
        var settings = AppSettings()
        settings.apiKey = "sk-secret"

        try store.save(settings)
        let loaded = try store.load()
        let attributes = try FileManager.default.attributesOfItem(atPath: root.appendingPathComponent("settings.json").path)

        #expect(loaded.apiKey == "sk-secret")
        #expect((attributes[.posixPermissions] as? NSNumber)?.intValue == 0o600)
    }

    @Test func pythonVersionRequiresThreeTenOrNewer() {
        #expect(!PythonRuntime.versionIsSupported("3.9.6"))
        #expect(PythonRuntime.versionIsSupported("3.10.0"))
        #expect(PythonRuntime.versionIsSupported("3.12.2"))
    }

    @Test func legacyBookRecordDecodesWithEmptyMetadata() throws {
        let data = Data(#"{"id":"00000000-0000-0000-0000-000000000001","title":"Legacy","sourceBookmark":"","sourcePathHint":"/tmp/a.epub","format":"epub","status":"idle","phase":"","progressLabel":"","stateDirectory":"/tmp/state","outputs":[]}"#.utf8)
        let book = try JSONDecoder().decode(BookRecord.self, from: data)
        #expect(book.metadata.authors.isEmpty)
        #expect(book.metadata.chapterCount == 0)
        #expect(book.completedSegments == 0)
        #expect(book.totalSegments == 0)
        #expect(book.completedChapters == 0)
        #expect(book.totalChapters == 0)
        #expect(book.accumulatedRunSeconds == 0)
        #expect(book.currentRunStartedAt == nil)
        #expect(book.lastRunHeartbeatAt == nil)
        #expect(!book.runtimeHistoryInitialized)
    }

    @Test func progressSnapshotReadsDurableChapterState() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let run = root.appendingPathComponent("run")
        let chapters = run.appendingPathComponent("chapters")
        defer { try? FileManager.default.removeItem(at: root) }
        try FileManager.default.createDirectory(at: chapters, withIntermediateDirectories: true)
        try Data(#"[{"index":0,"status":"done"},{"index":1,"status":"pending"}]"#.utf8).write(to: run.appendingPathComponent("manifest.json"))
        try Data(#"{"segments":[{"source":"a","target":"甲"},{"source":"b","target":"乙"}]}"#.utf8).write(to: chapters.appendingPathComponent("ch0.json"))
        try Data(#"{"segments":[{"source":"c","target":"丙"},{"source":"d","target":null}]}"#.utf8).write(to: chapters.appendingPathComponent("ch1.json"))

        let snapshot = try #require(ProgressSnapshotReader().read(stateDirectory: root.path))
        #expect(snapshot.completedSegments == 3)
        #expect(snapshot.totalSegments == 4)
        #expect(snapshot.completedChapters == 1)
        #expect(snapshot.totalChapters == 2)
        #expect(snapshot.fraction == 0.75)
    }

    @Test func progressPhaseDistinguishesPrescanFromTranslation() {
        #expect(ProgressPhaseResolver.phase(current: "准备图书", label: "全书理解预扫", completedSegments: 0) == "全书理解预扫")
        #expect(ProgressPhaseResolver.phase(current: "准备图书", label: "第一章", completedSegments: 1) == "正文翻译")
    }

    @Test func runtimeHistoryExcludesPauseBetweenRuns() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let run = root.appendingPathComponent("run")
        defer { try? FileManager.default.removeItem(at: root) }
        try FileManager.default.createDirectory(at: run, withIntermediateDirectories: true)
        let events = """
        {"ts":"2026-07-11T23:52:22+08:00","event":"translate_run_started"}
        {"ts":"2026-07-12T00:28:55+08:00","event":"batch_glossary_extracted"}
        {"ts":"2026-07-12T00:36:10+08:00","event":"run_resumed"}
        {"ts":"2026-07-12T00:36:10+08:00","event":"translate_run_started"}
        {"ts":"2026-07-12T00:53:46+08:00","event":"batch_translated"}
        """
        try events.data(using: .utf8)!.write(to: run.appendingPathComponent("events.jsonl"))

        let seconds = try #require(RuntimeHistoryReader().read(stateDirectory: root.path))
        #expect(seconds == 3_249)
    }

    @Test func runtimeClockSettlesAndFormatsElapsedTime() {
        let start = Date(timeIntervalSince1970: 100)
        var book = BookRecord(id: UUID(), title: "Book", sourceBookmark: Data(), sourcePathHint: "", format: "epub", accumulatedRunSeconds: 60, currentRunStartedAt: start, lastRunHeartbeatAt: Date(timeIntervalSince1970: 130), runtimeHistoryInitialized: true, stateDirectory: "/tmp")
        RuntimeClock.settle(&book, at: Date(timeIntervalSince1970: 140))
        #expect(book.accumulatedRunSeconds == 100)
        #expect(book.currentRunStartedAt == nil)
        #expect(book.lastRunHeartbeatAt == nil)
        #expect(RuntimeClock.formatted(100) == "1分40秒")
        #expect(RuntimeClock.formatted(7_694) == "2小时08分14秒")
    }

    @Test func interruptedRunOnlyCountsThroughLastHeartbeat() {
        var book = BookRecord(id: UUID(), title: "Book", sourceBookmark: Data(), sourcePathHint: "", format: "epub", accumulatedRunSeconds: 10, currentRunStartedAt: Date(timeIntervalSince1970: 100), lastRunHeartbeatAt: Date(timeIntervalSince1970: 125), runtimeHistoryInitialized: true, stateDirectory: "/tmp")
        RuntimeClock.recoverInterruptedRun(&book)
        #expect(book.accumulatedRunSeconds == 35)
        #expect(book.currentRunStartedAt == nil)
    }

    @MainActor @Test func sidebarSplitItemReceivesStrictWidthLimits() {
        let item = NSSplitViewItem(viewController: NSViewController())
        let splitView = NSSplitView()

        SidebarWidthPolicy.configure(item, in: splitView)

        #expect(item.minimumThickness == 180)
        #expect(item.maximumThickness == 280)
        #expect(item.canCollapse)
        #expect(splitView.autosaveName == "WenyiSidebarSplitView")
    }
}
