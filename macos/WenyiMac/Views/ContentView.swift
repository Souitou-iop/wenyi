import SwiftUI

struct ContentView: View {
    @Bindable var library: LibraryStore
    let manager: TranslationManager
    @State private var confirmingRemoval = false

    var body: some View {
        NavigationSplitView {
            List(library.books, selection: $library.selection) { book in
                BookRow(book: book).tag(book.id)
            }
            .listStyle(.sidebar)
            .navigationTitle("书架")
            .navigationSplitViewColumnWidth(
                min: SidebarWidthPolicy.minimum,
                ideal: SidebarWidthPolicy.ideal,
                max: SidebarWidthPolicy.maximum
            )
            .background {
                SidebarSplitViewConfigurator()
                    .frame(width: 0, height: 0)
            }
            .overlay { if library.books.isEmpty { ContentUnavailableView("还没有图书", systemImage: "books.vertical", description: Text("导入 EPUB、FB2 或 TXT 开始翻译")) } }
        } detail: {
            if let book = library.selectedBook { BookDetailView(book: book, manager: manager) }
            else { ContentUnavailableView("选择一本图书", systemImage: "book") }
        }
        .toolbar {
            ToolbarItemGroup {
                Button { library.importBooks() } label: { Label("导入", systemImage: "plus") }
                Button { if let book = library.selectedBook { manager.start(book) } } label: { Label("开始", systemImage: "play.fill") }.disabled(library.selectedBook?.status == .running)
                Button { if let book = library.selectedBook { manager.stop(book) } } label: { Label("停止", systemImage: "stop.fill") }.disabled(library.selectedBook?.status != .running)
                Button { if let book = library.selectedBook { library.relocate(book) } } label: { Label("重新定位", systemImage: "location") }.disabled(library.selectedBook?.status != .needsRelocation)
                Button(role: .destructive) { confirmingRemoval = true } label: { Label("移除", systemImage: "trash") }.disabled(library.selectedBook == nil)
                Spacer()
                RunningStatusView(count: library.runningCount)
            }
        }
        .confirmationDialog("移出书架并删除断点？", isPresented: $confirmingRemoval) {
            Button("移除并删除进度", role: .destructive) { if let book = library.selectedBook { manager.stop(book); library.remove(book) } }
        } message: { Text("不会删除原始图书和已经生成的译文。") }
    }
}

private struct RunningStatusView: View {
    let count: Int
    var body: some View {
        Text("正在运行 \(count)")
            .lineLimit(1)
            .fixedSize(horizontal: true, vertical: false)
            .frame(minWidth: 120)
            .layoutPriority(2)
    }
}

private struct BookRow: View {
    let book: BookRecord
    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: book.status == .completed ? "checkmark.circle.fill" : "book.closed").foregroundStyle(book.status == .failed ? .red : .secondary)
            VStack(alignment: .leading, spacing: 2) { Text(book.title).lineLimit(1); Text(book.status.label).font(.caption).foregroundStyle(.secondary) }
        }
    }
}

private struct BookDetailView: View {
    let book: BookRecord
    let manager: TranslationManager
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                HStack(alignment: .top, spacing: 24) {
                    BookCover(path: book.metadata.coverPath)
                    VStack(alignment: .leading, spacing: 8) {
                        Text(book.title).font(.largeTitle.bold())
                        MetadataLine(label: "作者", value: book.metadata.authors.joined(separator: "、"))
                        MetadataLine(label: "语言", value: book.metadata.language)
                        MetadataLine(label: "出版社", value: book.metadata.publisher)
                        MetadataLine(label: "出版日期", value: book.metadata.publicationDate)
                        MetadataLine(label: "标识符", value: book.metadata.identifier)
                        MetadataLine(label: "主题", value: book.metadata.subjects.joined(separator: "、"))
                        MetadataLine(label: "章节", value: book.metadata.chapterCount > 0 ? "\(book.metadata.chapterCount)" : "")
                        MetadataLine(label: "大小", value: book.metadata.fileSize > 0 ? ByteCountFormatter.string(fromByteCount: book.metadata.fileSize, countStyle: .file) : "")
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
                if !book.metadata.bookDescription.isEmpty { GroupBox("简介") { Text(book.metadata.bookDescription).frame(maxWidth: .infinity, alignment: .leading).textSelection(.enabled) } }
                Text(book.sourcePathHint).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                GroupBox("翻译状态") {
                    VStack(alignment: .leading, spacing: 10) {
                        HStack { Text(book.status.label).font(.headline); Spacer(); if !book.phase.isEmpty { Text(book.phase).foregroundStyle(.secondary) } }
                        if let progress = book.progress {
                            ProgressView(value: progress)
                            HStack(spacing: 16) {
                                Text(progress, format: .percent.precision(.fractionLength(1)))
                                if book.totalChapters > 0 { Text("章节 \(book.completedChapters)/\(book.totalChapters)") }
                                if book.totalSegments > 0 { Text("段落 \(book.completedSegments)/\(book.totalSegments)") }
                            }.font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                            RuntimeText(book: book)
                            if !book.progressLabel.isEmpty { Text(book.progressLabel).font(.caption).foregroundStyle(.secondary) }
                        }
                        else if book.status == .running { ProgressView().controlSize(.small) }
                        if let error = book.errorMessage { Text(error).foregroundStyle(.red).textSelection(.enabled) }
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
                if !book.outputs.isEmpty {
                    GroupBox("译文产物") { VStack(alignment: .leading) { ForEach(book.outputs, id: \.self) { path in HStack { Text(URL(fileURLWithPath: path).lastPathComponent); Spacer(); Button("打开") { NSWorkspace.shared.open(URL(fileURLWithPath: path)) }; Button("在 Finder 中显示") { NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)]) } } } }.frame(maxWidth: .infinity) }
                }
            }.padding(24)
        }
    }
}

private struct RuntimeText: View {
    let book: BookRecord
    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            Text("累计运行 \(RuntimeClock.formatted(RuntimeClock.elapsed(for: book, at: context.date)))")
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
        }
    }
}

private struct BookCover: View {
    let path: String?
    var body: some View {
        Group {
            if let path, let image = NSImage(contentsOfFile: path) { Image(nsImage: image).resizable().scaledToFit() }
            else { Image(systemName: "book.closed.fill").resizable().scaledToFit().padding(36).foregroundStyle(.secondary) }
        }.frame(width: 180, height: 250).background(.quaternary, in: RoundedRectangle(cornerRadius: 10)).clipShape(RoundedRectangle(cornerRadius: 10))
    }
}

private struct MetadataLine: View {
    let label: String; let value: String
    var body: some View { if !value.isEmpty { LabeledContent(label, value: value).textSelection(.enabled) } }
}
