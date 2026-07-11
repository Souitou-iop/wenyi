import Foundation

enum RuntimeClock {
    static func elapsed(for book: BookRecord, at date: Date = Date()) -> TimeInterval {
        guard let started = book.currentRunStartedAt else { return book.accumulatedRunSeconds }
        return book.accumulatedRunSeconds + max(0, date.timeIntervalSince(started))
    }

    static func settle(_ book: inout BookRecord, at date: Date = Date()) {
        if let started = book.currentRunStartedAt {
            book.accumulatedRunSeconds += max(0, date.timeIntervalSince(started))
        }
        book.currentRunStartedAt = nil
        book.lastRunHeartbeatAt = nil
    }

    static func recoverInterruptedRun(_ book: inout BookRecord) {
        if let started = book.currentRunStartedAt, let heartbeat = book.lastRunHeartbeatAt {
            book.accumulatedRunSeconds += max(0, heartbeat.timeIntervalSince(started))
        }
        book.currentRunStartedAt = nil
        book.lastRunHeartbeatAt = nil
    }

    static func formatted(_ interval: TimeInterval) -> String {
        let seconds = max(0, Int(interval.rounded(.down)))
        let hours = seconds / 3600
        let minutes = (seconds % 3600) / 60
        let remainder = seconds % 60
        if hours > 0 { return String(format: "%d小时%02d分%02d秒", hours, minutes, remainder) }
        return String(format: "%d分%02d秒", minutes, remainder)
    }
}

struct RuntimeHistoryReader {
    private struct Event: Decodable { let ts: Date; let event: String }

    func read(stateDirectory: String) -> TimeInterval? {
        let root = URL(fileURLWithPath: stateDirectory)
        guard let enumerator = FileManager.default.enumerator(at: root, includingPropertiesForKeys: nil),
              let eventsURL = enumerator.compactMap({ $0 as? URL }).first(where: { $0.lastPathComponent == "events.jsonl" }),
              let text = try? String(contentsOf: eventsURL, encoding: .utf8) else { return nil }
        let decoder = JSONDecoder(); decoder.dateDecodingStrategy = .iso8601
        let events = text.split(whereSeparator: \.isNewline).compactMap { try? decoder.decode(Event.self, from: Data($0.utf8)) }
        var total: TimeInterval = 0
        var start: Date?
        var last: Date?
        for event in events {
            if event.event == "run_resumed", let intervalStart = start, let intervalEnd = last {
                total += max(0, intervalEnd.timeIntervalSince(intervalStart))
                start = nil
                last = nil
            }
            if event.event == "translate_run_started" { start = event.ts }
            if start != nil { last = event.ts }
        }
        if let start, let last { total += max(0, last.timeIntervalSince(start)) }
        return total
    }
}
