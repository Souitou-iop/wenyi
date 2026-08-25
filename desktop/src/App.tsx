import React, { useEffect, useState } from "react";
import { Header } from "./components/Header";
import { BookshelfHero } from "./components/BookshelfHero";
import { DarkStatusTile } from "./components/DarkStatusTile";
import { LogViewer } from "./components/LogViewer";
import { SettingsView } from "./components/SettingsView";
import { BookMetadata, FullAppConfig, PythonEnvInfo, TaskSnapshot } from "./types";
import {
  detectPythonEnvironments,
  getCurrentTask,
  inspectBookFile,
  listenToTaskStatus,
  loadAppConfig,
  pickBookFile,
  saveAppConfig,
  setPreventSleep,
  startTranslation,
  stopTranslation,
} from "./api/tauri";

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<"translate" | "settings">("translate");
  const [config, setConfig] = useState<FullAppConfig | null>(null);
  const [pythonEnvs, setPythonEnvs] = useState<PythonEnvInfo[]>([]);
  const [selectedPythonPath, setSelectedPythonPath] = useState<string | null>(null);
  const [currentBook, setCurrentBook] = useState<BookMetadata | null>(null);
  const [currentTask, setCurrentTask] = useState<TaskSnapshot | null>(null);
  const [preventSleepState, setPreventSleepState] = useState<boolean>(true);
  const [isStarting, setIsStarting] = useState<boolean>(false);
  const [appError, setAppError] = useState<string | null>(null);

  // 初始化加载
  useEffect(() => {
    async function initApp() {
      try {
        const loadedCfg = await loadAppConfig();
        setConfig(loadedCfg);
        setPreventSleepState(loadedCfg.preferences.prevent_sleep);

        const envs = await detectPythonEnvironments(loadedCfg.preferences.custom_python_path || undefined);
        setPythonEnvs(envs);

        // 默认选中有文译模块的环境，或自定义环境
        if (loadedCfg.preferences.custom_python_path) {
          setSelectedPythonPath(loadedCfg.preferences.custom_python_path);
        } else {
          const best = envs.find((e) => e.hasWenyi) || envs.find((e) => e.isValid);
          if (best) setSelectedPythonPath(best.path);
        }

        const task = await getCurrentTask();
        if (task) {
          setCurrentTask(task);
          if (task.bookPath) {
            try {
              const bookMeta = await inspectBookFile(task.bookPath);
              setCurrentBook(bookMeta);
            } catch (err) {
              console.warn("无法加载历史任务书籍元数据", err);
            }
          }
        }
      } catch (err) {
        console.error("初始化应用数据失败", err);
        setAppError(String(err));
      }
    }

    initApp();

    // 监听任务状态事件
    let unlistenFn: (() => void) | undefined;
    listenToTaskStatus((snapshot) => {
      setCurrentTask(snapshot);
    }).then((unlisten) => {
      unlistenFn = unlisten;
    });

    return () => {
      if (unlistenFn) unlistenFn();
    };
  }, []);

  // 选择书籍
  const handlePickBook = async () => {
    try {
      const picked = await pickBookFile();
      if (picked) {
        setAppError(null);
        const metadata = await inspectBookFile(picked);
        setCurrentBook(metadata);
      }
    } catch (err) {
      setAppError(formatError(err));
    }
  };

  // 启动翻译
  const handleStartTranslation = async () => {
    if (!currentBook) return;
    setIsStarting(true);
    setAppError(null);
    try {
      const snapshot = await startTranslation({
        inputPath: currentBook.path,
        outFormat: currentBook.format,
      });
      setCurrentTask(snapshot);
    } catch (err) {
      setAppError(formatError(err));
    } finally {
      setIsStarting(false);
    }
  };

  // 停止翻译
  const handleStopTranslation = async () => {
    try {
      await stopTranslation();
    } catch (err) {
      setAppError(formatError(err));
    }
  };

  // 切换休眠锁
  const handleTogglePreventSleep = async () => {
    const nextState = !preventSleepState;
    try {
      const active = await setPreventSleep(nextState);
      setPreventSleepState(active);
      if (config) {
        const updatedCfg = {
          ...config,
          preferences: { ...config.preferences, prevent_sleep: active },
        };
        setConfig(updatedCfg);
        await saveAppConfig(updatedCfg);
      }
    } catch (err) {
      console.error("切换防休眠失败", err);
    }
  };

  // 刷新环境
  const handleRefreshEnvs = async () => {
    try {
      const envs = await detectPythonEnvironments(selectedPythonPath || undefined);
      setPythonEnvs(envs);
      if (!selectedPythonPath && envs.length > 0) {
        const best = envs.find((e) => e.hasWenyi) || envs.find((e) => e.isValid);
        if (best) setSelectedPythonPath(best.path);
      }
    } catch (err) {
      setAppError(formatError(err));
    }
  };

  // 保存配置
  const handleSaveConfig = async (newConfig: FullAppConfig) => {
    setConfig(newConfig);
    setPreventSleepState(newConfig.preferences.prevent_sleep);
    await saveAppConfig(newConfig);
  };

  const activeEnv = pythonEnvs.find((e) => e.path === selectedPythonPath) || pythonEnvs[0] || null;

  return (
    <div className="flex flex-col h-screen bg-apple-parchment text-apple-ink overflow-hidden">
      {/* 顶部全局导航 */}
      <Header
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        preventSleep={preventSleepState}
        onTogglePreventSleep={handleTogglePreventSleep}
        activeEnv={activeEnv}
      />

      {/* 错误提示条 */}
      {appError && (
        <div className="bg-rose-50 border-b border-rose-200 px-6 py-2.5 text-xs text-rose-700 flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <span className="font-bold">⚠️ 提示：</span>
            <span>{appError}</span>
          </div>
          <button
            onClick={() => setAppError(null)}
            className="text-rose-500 hover:text-rose-700 font-bold ml-4"
          >
            ✕
          </button>
        </div>
      )}

      {/* 主工作区 */}
      <main className="flex-1 overflow-y-auto p-6 md:p-8">
        {activeTab === "translate" ? (
          <div className="max-w-5xl mx-auto space-y-6">
            {/* 书籍选择 Hero 卡片 */}
            <BookshelfHero
              currentBook={currentBook}
              currentTask={currentTask}
              onPickBook={handlePickBook}
              onStartTranslation={handleStartTranslation}
              onStopTranslation={handleStopTranslation}
              isStarting={isStarting}
            />

            {/* Apple 标志性深色磁贴（进度与状态） */}
            <DarkStatusTile currentTask={currentTask} />

            {/* 实时终端日志与产物输出 */}
            <LogViewer currentTask={currentTask} />
          </div>
        ) : (
          config && (
            <SettingsView
              config={config}
              onSaveConfig={handleSaveConfig}
              pythonEnvs={pythonEnvs}
              onRefreshEnvs={handleRefreshEnvs}
              selectedPythonPath={selectedPythonPath}
              onSelectPythonPath={(path) => setSelectedPythonPath(path)}
            />
          )
        )}
      </main>
    </div>
  );
};

function formatError(err: unknown): string {
  if (typeof err === "string") return err;
  if (err instanceof Error) return err.message;
  return JSON.stringify(err);
}
