import CryptoKit
import Foundation
import Observation

@MainActor @Observable
final class PythonEnvironmentManager {
    var state: PythonEnvironmentState = .idle
    var log = ""
    private var process: Process?

    func ensure(basePython: String, force: Bool = false) async -> String? {
        guard let runtime = PythonDetector().probe(basePython), PythonRuntime.versionIsSupported(runtime.version) else {
            state = .failed("需要 Python 3.10 或更高版本")
            return nil
        }
        let fingerprint = SHA256.hash(data: Data("\(URL(fileURLWithPath: basePython).resolvingSymlinksInPath().path)|\(runtime.version)|wenyi-deps-v1".utf8)).map { String(format: "%02x", $0) }.joined().prefix(16)
        let root = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("文译/Python/\(fingerprint)/venv")
        let python = root.appendingPathComponent("bin/python3").path
        if force { try? FileManager.default.removeItem(at: root) }
        if FileManager.default.isExecutableFile(atPath: python), await healthy(python) { state = .ready(python); return python }

        state = .installing("创建专用 Python 环境")
        log = ""
        do {
            try FileManager.default.createDirectory(at: root.deletingLastPathComponent(), withIntermediateDirectories: true)
            try await run(basePython, ["-m", "venv", "--clear", root.path])
            state = .installing("安装文译依赖")
            try await run(python, ["-m", "pip", "install", "--upgrade", "pip"])
            try await run(python, ["-m", "pip", "install", "openai>=1.40", "pydantic>=2.7", "pyyaml>=6.0", "tenacity>=8.2", "beautifulsoup4>=4.12", "lxml>=5.0", "ebooklib>=0.18", "typer>=0.12", "rich>=13.7"])
            guard await healthy(python) else { throw NSError(domain: "PythonEnvironment", code: 2, userInfo: [NSLocalizedDescriptionKey: "依赖安装完成，但导入健康检查失败"]) }
            state = .ready(python); return python
        } catch {
            state = .failed(error.localizedDescription); return nil
        }
    }

    func cancel() { process?.terminate() }

    private func healthy(_ python: String) async -> Bool {
        (try? await run(python, ["-c", "import openai,pydantic,yaml,tenacity,bs4,lxml,ebooklib,typer,rich"])) != nil
    }

    @discardableResult private func run(_ executable: String, _ arguments: [String]) async throws -> String {
        let environment = cleanEnvironment()
        return try await Task.detached { [weak self] in
            let process = Process(); let pipe = Pipe()
            process.executableURL = URL(fileURLWithPath: executable); process.arguments = arguments; process.environment = environment; process.standardOutput = pipe; process.standardError = pipe
            await MainActor.run { self?.process = process }
            try process.run()
            let data = pipe.fileHandleForReading.readDataToEndOfFile(); process.waitUntilExit()
            let text = String(decoding: data, as: UTF8.self)
            await MainActor.run { self?.log += text; self?.process = nil }
            guard process.terminationStatus == 0 else { throw NSError(domain: "PythonEnvironment", code: Int(process.terminationStatus), userInfo: [NSLocalizedDescriptionKey: String(text.suffix(2000))]) }
            return text
        }.value
    }

    private func cleanEnvironment() -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        env.removeValue(forKey: "PYTHONHOME"); env.removeValue(forKey: "PYTHONPATH")
        env["PYTHONNOUSERSITE"] = "1"; env["PIP_CONFIG_FILE"] = "/dev/null"; env["PIP_USER"] = "0"; env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        return env
    }
}
