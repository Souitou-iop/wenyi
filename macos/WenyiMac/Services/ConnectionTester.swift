import Foundation

enum ConnectionTester {
    static func test(_ settings: AppSettings) async -> String {
        guard !settings.apiKey.isEmpty, let base = URL(string: settings.baseURL) else { return "请填写有效的端点和 API Key" }
        let url = base.appendingPathComponent("chat/completions")
        for tier in [settings.strong, settings.cheap, settings.fast] {
            var request = URLRequest(url: url); request.httpMethod = "POST"
            request.setValue("Bearer \(settings.apiKey)", forHTTPHeaderField: "Authorization")
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.timeoutInterval = TimeInterval(min(settings.timeout, 30))
            request.httpBody = try? JSONSerialization.data(withJSONObject: ["model": tier.model, "messages": [["role": "user", "content": "Reply OK"]], "max_tokens": 2])
            do {
                let (_, response) = try await URLSession.shared.data(for: request)
                guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { return "模型 \(tier.model) 验证失败" }
            } catch { return "连接失败：\(error.localizedDescription)" }
        }
        return "三档模型连接正常"
    }
}
