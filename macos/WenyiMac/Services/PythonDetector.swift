import Foundation

struct PythonDetector {
    static let packages = ["openai", "pydantic", "yaml", "tenacity", "bs4", "lxml", "ebooklib", "typer", "rich"]

    func detect() async -> [PythonRuntime] {
        var paths = ["/usr/bin/python3", "/opt/homebrew/bin/python3", "/usr/local/bin/python3"]
        let pyenvVersions = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".pyenv/versions")
        if let versions = try? FileManager.default.contentsOfDirectory(at: pyenvVersions, includingPropertiesForKeys: nil) {
            paths += versions.map { $0.appendingPathComponent("bin/python3").path }
        }
        paths += ["/Library/Frameworks/Python.framework/Versions/Current/bin/python3", "/opt/local/bin/python3"]
        paths += (ProcessInfo.processInfo.environment["PATH"] ?? "").split(separator: ":").map { "\($0)/python3" }
        if let shell = try? run("/bin/zsh", ["-lic", "command -v python3"]) { paths.append(shell.trimmingCharacters(in: .whitespacesAndNewlines)) }
        var seen = Set<String>()
        return paths.compactMap { path in
            let real = URL(fileURLWithPath: path).resolvingSymlinksInPath().path
            guard FileManager.default.isExecutableFile(atPath: real), seen.insert(real).inserted else { return nil }
            return probe(real)
        }.sorted { $0.version.compare($1.version, options: .numeric) == .orderedDescending }
    }

    func probe(_ path: String) -> PythonRuntime? {
        let imports = Self.packages.map { "try:\n import \($0)\nexcept Exception:\n missing.append('\($0)')" }.joined(separator: "\n")
        let script = "import json,platform\nmissing=[]\n\(imports)\nprint(json.dumps({'version':platform.python_version(),'missing':missing}))"
        guard let output = try? run(path, ["-c", script]), let data = output.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let version = object["version"] as? String, let missing = object["missing"] as? [String] else { return nil }
        return PythonRuntime(path: path, version: version, missingPackages: missing)
    }

    private func run(_ executable: String, _ arguments: [String]) throws -> String {
        let process = Process(); let pipe = Pipe()
        process.executableURL = URL(fileURLWithPath: executable); process.arguments = arguments; process.standardOutput = pipe
        try process.run(); process.waitUntilExit()
        return String(decoding: pipe.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
    }
}
