import Foundation

struct InspectedBook: Decodable {
    let title: String
    let authors: [String]
    let language: String
    let publisher: String
    let publicationDate: String
    let identifier: String
    let description: String
    let subjects: [String]
    let chapterCount: Int
    let fileSize: Int64
    let coverPath: String?
}

struct BookInspector {
    func inspect(url: URL, bookID: UUID, python: String) async throws -> InspectedBook {
        let resources = Bundle.main.resourceURL!
        let covers = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("文译/Covers")
        return try await Task.detached {
            let process = Process(); let output = Pipe(); let error = Pipe()
            process.executableURL = URL(fileURLWithPath: python)
            process.arguments = ["-m", "trans_novel.book_inspector", "--input", url.path, "--cover-directory", covers.path, "--book-id", bookID.uuidString]
            var env = ProcessInfo.processInfo.environment; env["PYTHONPATH"] = resources.path; env.removeValue(forKey: "PYTHONHOME"); process.environment = env; process.standardOutput = output; process.standardError = error
            try process.run(); process.waitUntilExit()
            guard process.terminationStatus == 0 else { throw NSError(domain: "BookInspector", code: Int(process.terminationStatus), userInfo: [NSLocalizedDescriptionKey: String(decoding: error.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)]) }
            return try JSONDecoder().decode(InspectedBook.self, from: output.fileHandleForReading.readDataToEndOfFile())
        }.value
    }
}
