import React, { useEffect, useRef } from "react";
import { Terminal, FolderOpen, FileCheck } from "lucide-react";
import { TaskSnapshot } from "../types";
import { openPathInFileManager } from "../api/tauri";

interface LogViewerProps {
  currentTask: TaskSnapshot | null;
}

export const LogViewer: React.FC<LogViewerProps> = ({ currentTask }) => {
  const logContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [currentTask?.recentLogs]);

  const hasOutputs = (currentTask?.outputs && currentTask.outputs.length > 0) || false;

  return (
    <div className="bg-apple-canvas rounded-apple-lg border border-apple-hairline p-5 shadow-sm flex flex-col flex-1 min-h-[220px]">
      {/* 头部标题 */}
      <div className="flex items-center justify-between pb-3 mb-3 border-b border-apple-hairline">
        <div className="flex items-center space-x-2">
          <Terminal className="w-4 h-4 text-apple-primary" />
          <h3 className="text-sm font-semibold text-apple-ink tracking-apple-headline">
            实时运行日志与输出
          </h3>
        </div>
        <span className="text-xs text-apple-ink-muted-48">
          {currentTask?.recentLogs.length || 0} 条事件
        </span>
      </div>

      {/* 产物通知栏（若有） */}
      {hasOutputs && (
        <div className="mb-3 p-3 bg-emerald-50 border border-emerald-200 rounded-apple-sm text-xs text-emerald-800 flex items-center justify-between">
          <div className="flex items-center space-x-2 truncate">
            <FileCheck className="w-4 h-4 text-emerald-600 flex-shrink-0" />
            <span className="truncate font-medium">
              产物已生成: {currentTask?.outputs.join(", ")}
            </span>
          </div>
          <button
            onClick={() => {
              if (currentTask?.outputs[0]) {
                openPathInFileManager(currentTask.outputs[0]);
              }
            }}
            className="ml-3 px-3 py-1 bg-emerald-600 hover:bg-emerald-700 text-white rounded-apple-pill font-medium flex items-center space-x-1 flex-shrink-0 transition-colors shadow-xs"
          >
            <FolderOpen className="w-3 h-3" />
            <span>打开目录</span>
          </button>
        </div>
      )}

      {/* 日志终端流视窗 */}
      <div
        ref={logContainerRef}
        className="flex-1 bg-apple-parchment/60 rounded-apple-sm p-3 border border-apple-hairline font-mono text-xs text-apple-ink-muted-80 overflow-y-auto space-y-1.5 max-h-[240px]"
      >
        {currentTask && currentTask.recentLogs.length > 0 ? (
          currentTask.recentLogs.map((log, index) => {
            const isError = log.includes("[Err]") || log.includes("❌");
            const isSuccess = log.includes("🎉") || log.includes("完成");
            return (
              <div
                key={index}
                className={`leading-relaxed break-all ${
                  isError
                    ? "text-rose-600 font-medium"
                    : isSuccess
                    ? "text-emerald-700 font-medium"
                    : "text-apple-ink-muted-80"
                }`}
              >
                <span className="text-apple-ink-muted-48 mr-2 select-none">
                  {String(index + 1).padStart(2, "0")}
                </span>
                {log}
              </div>
            );
          })
        ) : (
          <div className="text-apple-ink-muted-48 italic py-6 text-center">
            暂无活动日志。导入书籍并点击「开始翻译」后将在此实时显示多阶段流水线日志。
          </div>
        )}
      </div>
    </div>
  );
};
