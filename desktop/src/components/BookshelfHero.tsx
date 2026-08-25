import React from "react";
import { Plus, Play, Square, FileText } from "lucide-react";
import { BookMetadata, TaskSnapshot } from "../types";

interface BookshelfHeroProps {
  currentBook: BookMetadata | null;
  currentTask: TaskSnapshot | null;
  onPickBook: () => void;
  onStartTranslation: () => void;
  onStopTranslation: () => void;
  isStarting: boolean;
}

export const BookshelfHero: React.FC<BookshelfHeroProps> = ({
  currentBook,
  currentTask,
  onPickBook,
  onStartTranslation,
  onStopTranslation,
  isStarting,
}) => {
  const isRunning = currentTask?.status === "running";

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  };

  return (
    <div className="bg-apple-canvas rounded-apple-lg border border-apple-hairline p-6 shadow-sm transition-all duration-200">
      {currentBook ? (
        <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
          {/* 左侧：书籍封面与元数据 */}
          <div className="flex items-start space-x-5 flex-1 min-w-0">
            {/* 封面容器 */}
            <div className="w-24 h-32 rounded-apple-md bg-apple-parchment border border-apple-hairline flex-shrink-0 flex flex-col items-center justify-center overflow-hidden shadow-sm relative group">
              {currentBook.coverPath ? (
                <img
                  src={`asset://${currentBook.coverPath}`}
                  alt={currentBook.title}
                  className="w-full h-full object-cover"
                  onError={(e) => {
                    (e.target as HTMLElement).style.display = "none";
                  }}
                />
              ) : (
                <div className="flex flex-col items-center justify-center p-2 text-center">
                  <FileText className="w-8 h-8 text-apple-primary/70 mb-1" />
                  <span className="text-[10px] font-bold tracking-wider uppercase text-apple-ink-muted-80 bg-apple-pearl px-1.5 py-0.5 rounded border border-apple-hairline">
                    {currentBook.format}
                  </span>
                </div>
              )}
            </div>

            {/* 元数据说明 */}
            <div className="flex-1 min-w-0 pt-1">
              <div className="flex items-center space-x-2 mb-1">
                <span className="text-xs font-semibold uppercase px-2 py-0.5 bg-apple-parchment rounded-apple-sm text-apple-primary border border-apple-hairline">
                  {currentBook.format.toUpperCase()}
                </span>
                <span className="text-xs text-apple-ink-muted-48">
                  {formatFileSize(currentBook.fileSize)}
                </span>
              </div>

              <h2 className="text-2xl font-bold text-apple-ink tracking-apple-headline truncate mb-1" title={currentBook.title}>
                {currentBook.title}
              </h2>

              <p className="text-sm text-apple-ink-muted-80 truncate mb-3">
                {currentBook.authors.length > 0 ? `作者: ${currentBook.authors.join(", ")}` : "未知作者"}
                {" · "}
                <span>{currentBook.chapterCount} 个章节/片段</span>
              </p>

              <div className="flex items-center space-x-2 text-xs text-apple-ink-muted-48">
                <span className="truncate max-w-md bg-apple-parchment/60 px-2 py-1 rounded border border-apple-divider-soft" title={currentBook.path}>
                  {currentBook.path}
                </span>
              </div>
            </div>
          </div>

          {/* 右侧：主操作胶囊按钮 */}
          <div className="flex flex-col sm:flex-row items-center gap-3 w-full md:w-auto">
            <button
              onClick={onPickBook}
              disabled={isRunning || isStarting}
              className="w-full sm:w-auto px-5 py-2.5 rounded-apple-pill border border-apple-hairline bg-apple-canvas text-apple-ink hover:bg-apple-parchment text-sm font-medium transition-colors disabled:opacity-50"
            >
              更换书籍
            </button>

            {isRunning ? (
              <button
                onClick={onStopTranslation}
                className="w-full sm:w-auto px-6 py-2.5 rounded-apple-pill bg-rose-600 hover:bg-rose-700 text-white text-sm font-medium shadow-sm transition-all duration-150 flex items-center justify-center space-x-2"
              >
                <Square className="w-4 h-4 fill-current" />
                <span>停止任务</span>
              </button>
            ) : (
              <button
                onClick={onStartTranslation}
                disabled={isStarting}
                className="w-full sm:w-auto px-7 py-2.5 rounded-apple-pill bg-apple-primary hover:bg-apple-primary-focus text-white text-sm font-semibold shadow-sm hover:shadow transition-all duration-150 flex items-center justify-center space-x-2 disabled:opacity-50"
              >
                <Play className="w-4 h-4 fill-current" />
                <span>{isStarting ? "准备中..." : "开始翻译"}</span>
              </button>
            )}
          </div>
        </div>
      ) : (
        /* 空状态：引导导入书籍 */
        <div
          onClick={onPickBook}
          className="border-2 border-dashed border-apple-hairline hover:border-apple-primary/60 rounded-apple-md p-10 flex flex-col items-center justify-center text-center cursor-pointer transition-colors group bg-apple-pearl/30"
        >
          <div className="w-14 h-14 rounded-full bg-apple-parchment flex items-center justify-center text-apple-primary mb-4 group-hover:scale-105 transition-transform shadow-xs">
            <Plus className="w-7 h-7" />
          </div>
          <h3 className="text-lg font-semibold text-apple-ink tracking-apple-headline mb-1">
            选择或拖入待翻译的书籍文件
          </h3>
          <p className="text-sm text-apple-ink-muted-48 max-w-sm mb-4">
            支持 EPUB 原著小说、DOCX 文档、SRT 双语字幕文件及 Markdown / TXT 长文本
          </p>
          <span className="px-5 py-2 rounded-apple-pill bg-apple-primary text-white text-xs font-semibold shadow-sm group-hover:bg-apple-primary-focus transition-colors">
            浏览本地文件...
          </span>
        </div>
      )}
    </div>
  );
};
