import Foundation

enum BookTaskStatus: String, Codable, CaseIterable {
    case idle, running, paused, failed, completed, needsRelocation

    var label: String {
        switch self {
        case .idle: "未开始"
        case .running: "翻译中"
        case .paused: "已暂停"
        case .failed: "失败"
        case .completed: "已完成"
        case .needsRelocation: "需要重新定位"
        }
    }
}

struct BookMetadata: Codable, Hashable {
    var authors: [String] = []
    var language = ""
    var publisher = ""
    var publicationDate = ""
    var identifier = ""
    var bookDescription = ""
    var subjects: [String] = []
    var chapterCount = 0
    var fileSize: Int64 = 0
    var coverPath: String?
}

struct BookRecord: Identifiable, Codable, Hashable {
    var id: UUID
    var title: String
    var sourceBookmark: Data
    var sourcePathHint: String
    var format: String
    var status: BookTaskStatus = .idle
    var phase: String = ""
    var progress: Double?
    var progressLabel: String = ""
    var completedSegments = 0
    var totalSegments = 0
    var completedChapters = 0
    var totalChapters = 0
    var accumulatedRunSeconds: TimeInterval = 0
    var currentRunStartedAt: Date?
    var lastRunHeartbeatAt: Date?
    var runtimeHistoryInitialized = false
    var stateDirectory: String
    var outputs: [String] = []
    var errorMessage: String?
    var metadata = BookMetadata()

    private enum CodingKeys: String, CodingKey {
        case id, title, sourceBookmark, sourcePathHint, format, status, phase, progress, progressLabel, completedSegments, totalSegments, completedChapters, totalChapters, accumulatedRunSeconds, currentRunStartedAt, lastRunHeartbeatAt, runtimeHistoryInitialized, stateDirectory, outputs, errorMessage, metadata
    }

    init(id: UUID, title: String, sourceBookmark: Data, sourcePathHint: String, format: String, status: BookTaskStatus = .idle, phase: String = "", progress: Double? = nil, progressLabel: String = "", completedSegments: Int = 0, totalSegments: Int = 0, completedChapters: Int = 0, totalChapters: Int = 0, accumulatedRunSeconds: TimeInterval = 0, currentRunStartedAt: Date? = nil, lastRunHeartbeatAt: Date? = nil, runtimeHistoryInitialized: Bool = false, stateDirectory: String, outputs: [String] = [], errorMessage: String? = nil, metadata: BookMetadata = BookMetadata()) {
        self.id = id; self.title = title; self.sourceBookmark = sourceBookmark; self.sourcePathHint = sourcePathHint; self.format = format; self.status = status; self.phase = phase; self.progress = progress; self.progressLabel = progressLabel; self.completedSegments = completedSegments; self.totalSegments = totalSegments; self.completedChapters = completedChapters; self.totalChapters = totalChapters; self.accumulatedRunSeconds = accumulatedRunSeconds; self.currentRunStartedAt = currentRunStartedAt; self.lastRunHeartbeatAt = lastRunHeartbeatAt; self.runtimeHistoryInitialized = runtimeHistoryInitialized; self.stateDirectory = stateDirectory; self.outputs = outputs; self.errorMessage = errorMessage; self.metadata = metadata
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(UUID.self, forKey: .id); title = try c.decode(String.self, forKey: .title); sourceBookmark = try c.decode(Data.self, forKey: .sourceBookmark); sourcePathHint = try c.decode(String.self, forKey: .sourcePathHint); format = try c.decode(String.self, forKey: .format)
        status = try c.decodeIfPresent(BookTaskStatus.self, forKey: .status) ?? .idle; phase = try c.decodeIfPresent(String.self, forKey: .phase) ?? ""; progress = try c.decodeIfPresent(Double.self, forKey: .progress); progressLabel = try c.decodeIfPresent(String.self, forKey: .progressLabel) ?? ""; completedSegments = try c.decodeIfPresent(Int.self, forKey: .completedSegments) ?? 0; totalSegments = try c.decodeIfPresent(Int.self, forKey: .totalSegments) ?? 0; completedChapters = try c.decodeIfPresent(Int.self, forKey: .completedChapters) ?? 0; totalChapters = try c.decodeIfPresent(Int.self, forKey: .totalChapters) ?? 0; accumulatedRunSeconds = try c.decodeIfPresent(TimeInterval.self, forKey: .accumulatedRunSeconds) ?? 0; currentRunStartedAt = try c.decodeIfPresent(Date.self, forKey: .currentRunStartedAt); lastRunHeartbeatAt = try c.decodeIfPresent(Date.self, forKey: .lastRunHeartbeatAt); runtimeHistoryInitialized = try c.decodeIfPresent(Bool.self, forKey: .runtimeHistoryInitialized) ?? false; stateDirectory = try c.decode(String.self, forKey: .stateDirectory); outputs = try c.decodeIfPresent([String].self, forKey: .outputs) ?? []; errorMessage = try c.decodeIfPresent(String.self, forKey: .errorMessage); metadata = try c.decodeIfPresent(BookMetadata.self, forKey: .metadata) ?? BookMetadata()
    }
}

struct TierSettings: Codable, Hashable {
    var model: String
    var thinking: Bool
    var reasoningEffort: String
}

struct TranslationOptions: Codable, Hashable {
    var mono = true
    var bilingual = false
    var bilingualOrder = "target_first"
    var polish = true
    var review = true
    var autofixSevere = false
    var bookUnderstanding = true
    var consistencyQA = false
}

struct AppSettings: Codable, Hashable {
    var baseURL = "https://api.deepseek.com"
    var apiKey = ""
    var timeout = 600
    var maxRetries = 4
    var strong = TierSettings(model: "deepseek-v4-pro", thinking: true, reasoningEffort: "high")
    var cheap = TierSettings(model: "deepseek-v4-flash", thinking: true, reasoningEffort: "high")
    var fast = TierSettings(model: "deepseek-v4-flash", thinking: false, reasoningEffort: "high")
    var pythonPath = ""
    var managedPythonPath: String?
    var outputDirectoryBookmark: Data?
    var outputDirectoryHint = ""
    var options = TranslationOptions()
}

struct WorkerEvent: Decodable {
    let protocolVersion: Int
    let taskID: String
    let type: String
    let phase: String?
    let label: String?
    let fraction: Double?
    let completed: Int?
    let total: Int?
    let outputs: [String]?
    let message: String?
    let stateDirectory: String?
}

struct PythonRuntime: Identifiable, Hashable {
    var id: String { path }
    let path: String
    let version: String
    let missingPackages: [String]
    var isUsable: Bool { missingPackages.isEmpty && Self.versionIsSupported(version) }

    static func versionIsSupported(_ value: String) -> Bool {
        let parts = value.split(separator: ".").compactMap { Int($0) }
        guard parts.count >= 2 else { return false }
        return parts[0] > 3 || (parts[0] == 3 && parts[1] >= 10)
    }
}

enum PythonEnvironmentState: Equatable {
    case idle, installing(String), ready(String), failed(String)
}
