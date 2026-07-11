import AppKit
import SwiftUI

struct SettingsView: View {
    @Bindable var library: LibraryStore
    @State private var showKey = false
    @State private var connectionStatus = ""

    var body: some View {
        TabView {
            Form {
                TextField("Base URL", text: $library.settings.baseURL)
                HStack { if showKey { TextField("API Key", text: $library.settings.apiKey) } else { SecureField("API Key", text: $library.settings.apiKey) }; Toggle("显示", isOn: $showKey).toggleStyle(.button) }
                HStack { TextField("超时（秒）", value: $library.settings.timeout, format: .number); TextField("重试次数", value: $library.settings.maxRetries, format: .number) }
                TierEditor(title: "Strong", tier: $library.settings.strong)
                TierEditor(title: "Cheap", tier: $library.settings.cheap)
                TierEditor(title: "Fast", tier: $library.settings.fast)
                HStack { Button("保存") { library.saveSettings() }; Button("测试连接") { Task { connectionStatus = await ConnectionTester.test(library.settings) } }; Button("清除 API Key", role: .destructive) { library.settings.apiKey = ""; library.saveSettings() }; Text(connectionStatus).foregroundStyle(.secondary) }
                Text("API Key 以当前用户私有的本地明文文件保存，不使用 Keychain。").font(.caption).foregroundStyle(.secondary)
            }.padding().tabItem { Label("模型", systemImage: "sparkles") }

            Form {
                Section("Python 环境") {
                    PythonEnvironmentStatus(state: library.pythonEnvironment.state, configuredVersion: configuredPythonVersion)
                    Button(library.settings.managedPythonPath == nil ? "一键配置" : "重新检测") {
                        library.configurePythonAutomatically()
                    }
                    .disabled(isConfiguring)
                    Text("仅在点击后检测本机 Python，并创建文译专用环境；不会修改原 Python。")
                        .font(.caption)
                        .foregroundStyle(.secondary)

                    DisclosureGroup("高级选项") {
                        VStack(alignment: .leading, spacing: 10) {
                            LabeledContent("基础 Python", value: library.settings.pythonPath.isEmpty ? "尚未选择" : library.settings.pythonPath)
                            if let managed = library.settings.managedPythonPath {
                                LabeledContent("专用环境", value: managed)
                            }
                            Button("手动选择 Python…") { choosePython() }
                            Button("重新安装专用环境", role: .destructive) { library.installPythonEnvironment(force: true) }
                                .disabled(library.settings.pythonPath.isEmpty || isConfiguring)
                            if !library.pythonEnvironment.log.isEmpty {
                                DisclosureGroup("安装日志") {
                                    ScrollView {
                                        Text(library.pythonEnvironment.log)
                                            .font(.caption.monospaced())
                                            .textSelection(.enabled)
                                            .frame(maxWidth: .infinity, alignment: .leading)
                                    }
                                    .frame(height: 120)
                                }
                            }
                        }
                        .padding(.top, 6)
                    }
                }
                Divider()
                LabeledContent("输出目录", value: library.settings.outputDirectoryHint.isEmpty ? "尚未选择" : library.settings.outputDirectoryHint)
                Button("选择输出目录…") { chooseOutput() }
            }.padding().tabItem { Label("运行环境", systemImage: "terminal") }

            Form {
                Toggle("生成单语版", isOn: $library.settings.options.mono)
                Toggle("生成双语版", isOn: $library.settings.options.bilingual)
                Picker("双语顺序", selection: $library.settings.options.bilingualOrder) { Text("译文在上").tag("target_first"); Text("原文在上").tag("source_first") }
                Toggle("翻译后润色", isOn: $library.settings.options.polish)
                Toggle("章末审校", isOn: $library.settings.options.review)
                Toggle("严重问题自动修复", isOn: $library.settings.options.autofixSevere)
                Toggle("全书理解预扫", isOn: $library.settings.options.bookUnderstanding)
                Toggle("全书一致性 QA", isOn: $library.settings.options.consistencyQA)
                Button("保存") { library.saveSettings() }.disabled(!library.settings.options.mono && !library.settings.options.bilingual)
            }.padding().tabItem { Label("翻译", systemImage: "character.book.closed") }
        }.frame(width: 620, height: 520)
    }

    private var isConfiguring: Bool {
        if case .installing = library.pythonEnvironment.state { return true }
        return false
    }

    private var configuredPythonVersion: String? {
        guard let runtime = library.runtimes.first(where: { $0.path == library.settings.pythonPath }) else { return nil }
        return runtime.version
    }

    private func choosePython() { let p = NSOpenPanel(); p.canChooseFiles = true; p.canChooseDirectories = false; if p.runModal() == .OK, let url = p.url { library.settings.pythonPath = url.resolvingSymlinksInPath().path; library.settings.managedPythonPath = nil; library.saveSettings() } }
    private func chooseOutput() { let p = NSOpenPanel(); p.canChooseFiles = false; p.canChooseDirectories = true; if p.runModal() == .OK, let url = p.url, let data = try? url.bookmarkData(options: [.withSecurityScope]) { library.settings.outputDirectoryBookmark = data; library.settings.outputDirectoryHint = url.path; library.saveSettings() } }
}

private struct PythonEnvironmentStatus: View {
    let state: PythonEnvironmentState
    let configuredVersion: String?

    var body: some View {
        HStack(spacing: 12) {
            statusIcon
                .font(.title2)
                .frame(width: 28)
            VStack(alignment: .leading, spacing: 3) {
                Text(title).font(.headline)
                Text(detail).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            if case .installing = state { ProgressView().controlSize(.small) }
        }
        .padding(12)
        .background(.quaternary, in: RoundedRectangle(cornerRadius: 10))
    }

    @ViewBuilder private var statusIcon: some View {
        switch state {
        case .ready: Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
        case .failed: Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange)
        case .installing: Image(systemName: "gearshape.2.fill").foregroundStyle(.blue)
        case .idle: Image(systemName: "terminal").foregroundStyle(.secondary)
        }
    }

    private var title: String {
        switch state {
        case .ready: "环境已就绪"
        case .failed: "配置失败"
        case .installing: "正在配置运行环境…"
        case .idle: "尚未配置"
        }
    }

    private var detail: String {
        switch state {
        case .ready: configuredVersion.map { "Python \($0) · 文译专用环境" } ?? "文译专用环境"
        case .failed(let message), .installing(let message): message
        case .idle: "点击一键配置即可自动完成"
        }
    }
}

private struct TierEditor: View {
    let title: String
    @Binding var tier: TierSettings
    var body: some View { GroupBox(title) { VStack { TextField("模型", text: $tier.model); Toggle("Thinking", isOn: $tier.thinking); Picker("Reasoning effort", selection: $tier.reasoningEffort) { Text("Low").tag("low"); Text("Medium").tag("medium"); Text("High").tag("high") } }.padding(.vertical, 4) } }
}
