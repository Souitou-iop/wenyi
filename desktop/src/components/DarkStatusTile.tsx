import React from "react";
import { CheckCircle2, AlertTriangle, Sparkles, Loader2 } from "lucide-react";
import { TaskSnapshot } from "../types";

interface DarkStatusTileProps {
  currentTask: TaskSnapshot | null;
}

export const DarkStatusTile: React.FC<DarkStatusTileProps> = ({ currentTask }) => {
  const isRunning = currentTask?.status === "running";
  const isCompleted = currentTask?.status === "completed";
  const isFailed = currentTask?.status === "failed";
  const isCancelled = currentTask?.status === "cancelled";

  const progressPercent = currentTask
    ? Math.min(100, Math.max(0, Math.round(currentTask.progressFraction * 100)))
    : 0;

  return (
    <div className="bg-apple-tile-1 text-white rounded-apple-lg p-6 shadow-md border border-white/5 relative overflow-hidden">
      {/* 顶部：阶段徽章与状态 */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center space-x-2.5">
          <div className="p-1.5 rounded-apple-sm bg-white/10 text-apple-primary-on-dark flex items-center justify-center">
            {isRunning ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : isCompleted ? (
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            ) : isFailed ? (
              <AlertTriangle className="w-4 h-4 text-rose-400" />
            ) : (
              <Sparkles className="w-4 h-4 text-sky-400" />
            )}
          </div>
          <div>
            <span className="text-xs font-semibold uppercase tracking-wider text-apple-primary-on-dark block">
              {currentTask?.currentPhase ? `当前阶段: ${currentTask.currentPhase}` : "任务调度中心"}
            </span>
            <h3 className="text-lg font-bold text-white tracking-apple-headline leading-tight">
              {currentTask ? currentTask.phaseLabel : "等待启动翻译任务"}
            </h3>
          </div>
        </div>

        {/* 状态药丸徽章 */}
        <div>
          {isRunning && (
            <span className="px-3 py-1 rounded-apple-pill text-xs font-medium bg-sky-500/20 text-sky-300 border border-sky-500/30 flex items-center space-x-1.5">
              <span className="w-2 h-2 rounded-full bg-sky-400 animate-pulse" />
              <span>正在流水线翻译</span>
            </span>
          )}
          {isCompleted && (
            <span className="px-3 py-1 rounded-apple-pill text-xs font-medium bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
              整书翻译完成
            </span>
          )}
          {isFailed && (
            <span className="px-3 py-1 rounded-apple-pill text-xs font-medium bg-rose-500/20 text-rose-300 border border-rose-500/30">
              执行异常
            </span>
          )}
          {isCancelled && (
            <span className="px-3 py-1 rounded-apple-pill text-xs font-medium bg-amber-500/20 text-amber-300 border border-amber-500/30">
              任务已中止
            </span>
          )}
          {!currentTask && (
            <span className="px-3 py-1 rounded-apple-pill text-xs font-medium bg-white/10 text-white/60 border border-white/10">
              空闲待命
            </span>
          )}
        </div>
      </div>

      {/* 中部：进度条 */}
      <div className="mb-4">
        <div className="flex justify-between text-xs text-white/70 mb-1.5 font-medium">
          <span>整体完成进度</span>
          <span className="text-apple-primary-on-dark font-mono font-bold text-sm">
            {progressPercent}%
          </span>
        </div>
        <div className="w-full h-3 bg-white/10 rounded-apple-pill overflow-hidden p-0.5 border border-white/5">
          <div
            className="h-full bg-gradient-to-r from-sky-500 to-apple-primary-on-dark rounded-apple-pill transition-all duration-300 ease-out shadow-sm"
            style={{ width: `${progressPercent}%` }}
          />
        </div>
      </div>

      {/* 底部：指标网格 */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-3 border-t border-white/10 text-xs">
        <div>
          <span className="text-white/50 block mb-0.5">已处理单元</span>
          <span className="text-white font-mono font-medium">
            {currentTask ? `${currentTask.completedUnits} / ${currentTask.totalUnits}` : "0 / 0"}
          </span>
        </div>

        <div>
          <span className="text-white/50 block mb-0.5">任务标识</span>
          <span className="text-white font-mono truncate block" title={currentTask?.taskId}>
            {currentTask ? currentTask.taskId.slice(0, 12) + "..." : "无"}
          </span>
        </div>

        <div>
          <span className="text-white/50 block mb-0.5">检查点目录</span>
          <span className="text-white truncate block" title={currentTask?.stateDir}>
            {currentTask ? currentTask.stateDir.split("/").pop() || "state" : "无"}
          </span>
        </div>

        <div>
          <span className="text-white/50 block mb-0.5">更新时间</span>
          <span className="text-white font-mono truncate block">
            {currentTask?.updatedAt ? new Date(currentTask.updatedAt).toLocaleTimeString() : "--:--:--"}
          </span>
        </div>
      </div>
    </div>
  );
};
