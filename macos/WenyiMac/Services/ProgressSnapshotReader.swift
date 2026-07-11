import Foundation

struct ProgressSnapshot {
    let completedSegments: Int
    let totalSegments: Int
    let completedChapters: Int
    let totalChapters: Int
    var fraction: Double? { totalSegments > 0 ? Double(completedSegments) / Double(totalSegments) : nil }
}

struct ProgressSnapshotReader {
    func read(stateDirectory: String) -> ProgressSnapshot? {
        let root = URL(fileURLWithPath: stateDirectory)
        guard let enumerator = FileManager.default.enumerator(at: root, includingPropertiesForKeys: nil),
              let manifest = enumerator.compactMap({ $0 as? URL }).first(where: { $0.lastPathComponent == "manifest.json" }),
              let data = try? Data(contentsOf: manifest),
              let decoded = try? JSONSerialization.jsonObject(with: data) else { return nil }
        let chapters: [[String: Any]]
        if let array = decoded as? [[String: Any]] { chapters = array }
        else if let object = decoded as? [String: Any], let array = object["chapters"] as? [[String: Any]] { chapters = array }
        else { return nil }
        let chaptersDirectory = manifest.deletingLastPathComponent().appendingPathComponent("chapters")
        var completedSegments = 0; var totalSegments = 0
        for chapter in chapters {
            guard let index = chapter["index"] as? Int,
                  let chapterData = try? Data(contentsOf: chaptersDirectory.appendingPathComponent("ch\(index).json")),
                  let chapterObject = try? JSONSerialization.jsonObject(with: chapterData) as? [String: Any],
                  let segments = chapterObject["segments"] as? [[String: Any]] else { continue }
            for segment in segments where !(segment["source"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                totalSegments += 1
                if !(segment["target"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { completedSegments += 1 }
            }
        }
        return ProgressSnapshot(completedSegments: completedSegments, totalSegments: totalSegments, completedChapters: chapters.filter { ($0["status"] as? String) == "done" }.count, totalChapters: chapters.count)
    }
}

enum ProgressPhaseResolver {
    static func phase(current: String, label: String, completedSegments: Int) -> String {
        if label.contains("预扫") { return "全书理解预扫" }
        if completedSegments > 0 || !label.isEmpty { return "正文翻译" }
        return current
    }
}
