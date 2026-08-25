import React from "react";
import { BookOpen, Settings, Moon, Sun } from "lucide-react";
import { PythonEnvInfo } from "../types";

interface HeaderProps {
  activeTab: "translate" | "settings";
  setActiveTab: (tab: "translate" | "settings") => void;
  preventSleep: boolean;
  onTogglePreventSleep: () => void;
  activeEnv: PythonEnvInfo | null;
}

export const Header: React.FC<HeaderProps> = ({
  activeTab,
  setActiveTab,
  preventSleep,
  onTogglePreventSleep,
  activeEnv,
}) => {
  return (
    <header className="h-16 px-6 border-b border-apple-hairline bg-apple-pearl/80 apple-frosted flex items-center justify-between app-drag-region sticky top-0 z-30">
      {/* 左侧：macOS 交通灯留白 + 品牌标题 */}
      <div className="flex items-center space-x-3 pl-16">
        <div className="w-8 h-8 rounded-apple-sm bg-apple-primary flex items-center justify-center text-white shadow-sm">
          <BookOpen className="w-4 h-4" />
        </div>
        <div>
          <h1 className="text-[17px] font-semibold text-apple-ink tracking-apple-headline leading-tight">
            文译 <span className="text-xs font-normal text-apple-ink-muted-48 ml-1">Desktop</span>
          </h1>
        </div>
      </div>

      {/* 中间：Apple 风格分段胶囊选择器 */}
      <div className="flex items-center bg-apple-parchment p-1 rounded-apple-pill border border-apple-hairline app-no-drag">
        <button
          onClick={() => setActiveTab("translate")}
          className={`px-5 py-1.5 rounded-apple-pill text-xs font-medium transition-all duration-150 flex items-center space-x-1.5 ${
            activeTab === "translate"
              ? "bg-apple-canvas text-apple-primary shadow-sm font-semibold"
              : "text-apple-ink-muted-80 hover:text-apple-ink"
          }`}
        >
          <BookOpen className="w-3.5 h-3.5" />
          <span>书籍翻译</span>
        </button>

        <button
          onClick={() => setActiveTab("settings")}
          className={`px-5 py-1.5 rounded-apple-pill text-xs font-medium transition-all duration-150 flex items-center space-x-1.5 ${
            activeTab === "settings"
              ? "bg-apple-canvas text-apple-primary shadow-sm font-semibold"
              : "text-apple-ink-muted-80 hover:text-apple-ink"
          }`}
        >
          <Settings className="w-3.5 h-3.5" />
          <span>系统设置</span>
        </button>
      </div>

      {/* 右侧：防休眠胶囊开关 + 环境状态指示灯 */}
      <div className="flex items-center space-x-3 app-no-drag">
        {/* 防休眠切换 */}
        <button
          onClick={onTogglePreventSleep}
          title="点击切换长时间翻译防系统休眠"
          className={`px-3 py-1 rounded-apple-pill text-xs font-medium border transition-colors flex items-center space-x-1.5 ${
            preventSleep
              ? "bg-apple-primary/10 border-apple-primary/30 text-apple-primary"
              : "bg-apple-canvas border-apple-hairline text-apple-ink-muted-48 hover:text-apple-ink"
          }`}
        >
          {preventSleep ? <Moon className="w-3.5 h-3.5" /> : <Sun className="w-3.5 h-3.5" />}
          <span>休眠锁: {preventSleep ? "开启" : "关闭"}</span>
        </button>

        {/* Python 状态胶囊 */}
        <div
          onClick={() => setActiveTab("settings")}
          className="cursor-pointer px-3 py-1 rounded-apple-pill text-xs font-medium bg-apple-canvas border border-apple-hairline text-apple-ink-muted-80 flex items-center space-x-1.5 hover:border-apple-primary/40 transition-colors"
          title={activeEnv ? `${activeEnv.name} (${activeEnv.path})` : "未检测到可用 Python 环境"}
        >
          <div
            className={`w-2 h-2 rounded-full ${
              activeEnv?.hasWenyi
                ? "bg-emerald-500 shadow-sm"
                : activeEnv?.isValid
                ? "bg-amber-500"
                : "bg-rose-500"
            }`}
          />
          <span className="max-w-[120px] truncate">
            {activeEnv?.hasWenyi ? `Python ${activeEnv.version}` : activeEnv ? "缺少核心依赖" : "未选环境"}
          </span>
        </div>
      </div>
    </header>
  );
};
