import React, { useState } from "react";
import {
  Cpu,
  Key,
  Folder,
  Check,
  RefreshCw,
  Eye,
  EyeOff,
  AlertCircle,
  CheckCircle2,
  FileSearch,
  Save,
  Moon,
  Bell,
} from "lucide-react";
import { FullAppConfig, PythonEnvInfo } from "../types";
import { pickPythonBinary, validatePythonExecutable } from "../api/tauri";

interface SettingsViewProps {
  config: FullAppConfig;
  onSaveConfig: (newConfig: FullAppConfig) => Promise<void>;
  pythonEnvs: PythonEnvInfo[];
  onRefreshEnvs: () => Promise<void>;
  selectedPythonPath: string | null;
  onSelectPythonPath: (path: string) => void;
}

export const SettingsView: React.FC<SettingsViewProps> = ({
  config,
  onSaveConfig,
  pythonEnvs,
  onRefreshEnvs,
  selectedPythonPath,
  onSelectPythonPath,
}) => {
  const [formData, setFormData] = useState<FullAppConfig>(config);
  const [showApiKey, setShowApiKey] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [customPathInput, setCustomPathInput] = useState(
    config.preferences.custom_python_path || ""
  );

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    try {
      const updatedConfig: FullAppConfig = {
        ...formData,
        preferences: {
          ...formData.preferences,
          custom_python_path: customPathInput.trim() || null,
        },
      };
      await onSaveConfig(updatedConfig);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 2500);
    } finally {
      setIsSaving(false);
    }
  };

  const handleBrowsePython = async () => {
    const picked = await pickPythonBinary();
    if (picked) {
      setCustomPathInput(picked);
      onSelectPythonPath(picked);
      await validatePythonExecutable(picked);
      await onRefreshEnvs();
    }
  };

  const handleRefresh = async () => {
    setIsRefreshing(true);
    try {
      await onRefreshEnvs();
    } finally {
      setIsRefreshing(false);
    }
  };

  return (
    <form onSubmit={handleSave} className="space-y-6 max-w-4xl mx-auto pb-10">
      {/* 模块 1：Python 运行环境 (BYOP) */}
      <div className="bg-apple-canvas rounded-apple-lg border border-apple-hairline p-6 shadow-sm">
        <div className="flex items-center justify-between pb-4 mb-4 border-b border-apple-hairline">
          <div className="flex items-center space-x-2.5">
            <div className="w-8 h-8 rounded-apple-sm bg-apple-parchment flex items-center justify-center text-apple-primary">
              <Cpu className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-apple-ink tracking-apple-headline">
                Python 运行环境 (Bring Your Own Python)
              </h2>
              <p className="text-xs text-apple-ink-muted-48">
                桌面端保持轻量，自动检测本机 Python、uv 或虚拟环境以执行翻译引擎
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={handleRefresh}
            disabled={isRefreshing}
            className="px-3 py-1.5 rounded-apple-pill border border-apple-hairline text-xs font-medium text-apple-ink hover:bg-apple-parchment flex items-center space-x-1.5 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? "animate-spin" : ""}`} />
            <span>重新探测</span>
          </button>
        </div>

        {/* 环境列表 */}
        <div className="space-y-2.5 mb-4">
          {pythonEnvs.map((env) => {
            const isSelected = selectedPythonPath === env.path;
            return (
              <div
                key={env.id}
                onClick={() => {
                  onSelectPythonPath(env.path);
                  setCustomPathInput(env.path);
                }}
                className={`p-3.5 rounded-apple-md border cursor-pointer transition-all duration-150 flex items-center justify-between ${
                  isSelected
                    ? "bg-apple-primary/5 border-apple-primary ring-1 ring-apple-primary/20"
                    : "bg-apple-parchment/40 border-apple-hairline hover:bg-apple-parchment"
                }`}
              >
                <div className="flex items-start space-x-3 min-w-0 flex-1">
                  <div
                    className={`w-4 h-4 rounded-full border mt-0.5 flex items-center justify-center flex-shrink-0 ${
                      isSelected
                        ? "border-apple-primary bg-apple-primary text-white"
                        : "border-apple-hairline bg-apple-canvas"
                    }`}
                  >
                    {isSelected && <Check className="w-2.5 h-2.5" />}
                  </div>

                  <div className="min-w-0 flex-1">
                    <div className="flex items-center space-x-2">
                      <span className="text-sm font-semibold text-apple-ink">
                        {env.name}
                      </span>
                      <span className="text-xs font-mono bg-apple-canvas px-1.5 py-0.5 rounded border border-apple-hairline text-apple-ink-muted-80">
                        v{env.version}
                      </span>
                      {env.hasWenyi ? (
                        <span className="text-[10px] font-medium px-1.5 py-0.5 bg-emerald-100 text-emerald-800 rounded flex items-center space-x-1">
                          <CheckCircle2 className="w-2.5 h-2.5" />
                          <span>就绪</span>
                        </span>
                      ) : (
                        <span className="text-[10px] font-medium px-1.5 py-0.5 bg-amber-100 text-amber-800 rounded flex items-center space-x-1">
                          <AlertCircle className="w-2.5 h-2.5" />
                          <span>缺模块</span>
                        </span>
                      )}
                    </div>

                    <p className="text-xs font-mono text-apple-ink-muted-48 truncate mt-0.5" title={env.path}>
                      {env.path}
                    </p>
                    <p className="text-[11px] text-apple-ink-muted-80 mt-1">
                      {env.statusMessage}
                    </p>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* 手动指定路径 */}
        <div className="pt-3 border-t border-apple-hairline">
          <label className="block text-xs font-semibold text-apple-ink mb-1.5">
            手动指定 Python 可执行文件路径
          </label>
          <div className="flex space-x-2">
            <input
              type="text"
              value={customPathInput}
              onChange={(e) => {
                setCustomPathInput(e.target.value);
                onSelectPythonPath(e.target.value);
              }}
              placeholder="例如: /usr/local/bin/python3 或 C:\Python312\python.exe"
              className="flex-1 bg-apple-parchment/60 border border-apple-hairline rounded-apple-sm px-3 py-2 text-xs font-mono text-apple-ink focus:outline-none focus:border-apple-primary focus:bg-apple-canvas transition-colors"
            />
            <button
              type="button"
              onClick={handleBrowsePython}
              className="px-4 py-2 bg-apple-canvas border border-apple-hairline hover:bg-apple-parchment rounded-apple-sm text-xs font-medium text-apple-ink flex items-center space-x-1.5 transition-colors shadow-xs"
            >
              <FileSearch className="w-3.5 h-3.5" />
              <span>选择文件</span>
            </button>
          </div>
        </div>
      </div>

      {/* 模块 2：LLM 模型与 API Key 配置 */}
      <div className="bg-apple-canvas rounded-apple-lg border border-apple-hairline p-6 shadow-sm">
        <div className="flex items-center space-x-2.5 pb-4 mb-4 border-b border-apple-hairline">
          <div className="w-8 h-8 rounded-apple-sm bg-apple-parchment flex items-center justify-center text-apple-primary">
            <Key className="w-4 h-4" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-apple-ink tracking-apple-headline">
              LLM 模型与 API 密钥
            </h2>
            <p className="text-xs text-apple-ink-muted-48">
              配置将直接同步至项目根目录的 config.yaml 文件
            </p>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* API Base URL */}
          <div className="md:col-span-2">
            <label className="block text-xs font-semibold text-apple-ink mb-1">
              API Base URL
            </label>
            <input
              type="text"
              value={formData.llm.api_base}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  llm: { ...formData.llm, api_base: e.target.value },
                })
              }
              placeholder="https://api.openai.com/v1"
              className="w-full bg-apple-parchment/60 border border-apple-hairline rounded-apple-sm px-3 py-2 text-xs font-mono text-apple-ink focus:outline-none focus:border-apple-primary focus:bg-apple-canvas transition-colors"
            />
          </div>

          {/* API Key */}
          <div className="md:col-span-2">
            <label className="block text-xs font-semibold text-apple-ink mb-1">
              API Key (密钥)
            </label>
            <div className="relative">
              <input
                type={showApiKey ? "text" : "password"}
                value={formData.llm.api_key}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    llm: { ...formData.llm, api_key: e.target.value },
                  })
                }
                placeholder="sk-..."
                className="w-full bg-apple-parchment/60 border border-apple-hairline rounded-apple-sm px-3 py-2 pr-10 text-xs font-mono text-apple-ink focus:outline-none focus:border-apple-primary focus:bg-apple-canvas transition-colors"
              />
              <button
                type="button"
                onClick={() => setShowApiKey(!showApiKey)}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-apple-ink-muted-48 hover:text-apple-ink"
              >
                {showApiKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          {/* Model Name */}
          <div>
            <label className="block text-xs font-semibold text-apple-ink mb-1">
              模型名称 (Model)
            </label>
            <input
              type="text"
              value={formData.llm.model}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  llm: { ...formData.llm, model: e.target.value },
                })
              }
              placeholder="gpt-4o-mini / deepseek-chat"
              className="w-full bg-apple-parchment/60 border border-apple-hairline rounded-apple-sm px-3 py-2 text-xs font-mono text-apple-ink focus:outline-none focus:border-apple-primary focus:bg-apple-canvas transition-colors"
            />
          </div>

          {/* Temperature */}
          <div>
            <label className="block text-xs font-semibold text-apple-ink mb-1">
              采样温度 (Temperature): {formData.llm.temperature}
            </label>
            <input
              type="range"
              min="0.0"
              max="1.0"
              step="0.05"
              value={formData.llm.temperature}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  llm: { ...formData.llm, temperature: parseFloat(e.target.value) },
                })
              }
              className="w-full h-2 bg-apple-parchment rounded-apple-pill appearance-none cursor-pointer accent-apple-primary mt-2"
            />
          </div>

          {/* Timeout */}
          <div>
            <label className="block text-xs font-semibold text-apple-ink mb-1">
              超时时长 (秒)
            </label>
            <input
              type="number"
              value={formData.llm.timeout}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  llm: { ...formData.llm, timeout: parseInt(e.target.value) || 120 },
                })
              }
              className="w-full bg-apple-parchment/60 border border-apple-hairline rounded-apple-sm px-3 py-2 text-xs text-apple-ink focus:outline-none focus:border-apple-primary focus:bg-apple-canvas transition-colors"
            />
          </div>

          {/* Max Retries */}
          <div>
            <label className="block text-xs font-semibold text-apple-ink mb-1">
              最大重试次数
            </label>
            <input
              type="number"
              value={formData.llm.max_retries}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  llm: { ...formData.llm, max_retries: parseInt(e.target.value) || 3 },
                })
              }
              className="w-full bg-apple-parchment/60 border border-apple-hairline rounded-apple-sm px-3 py-2 text-xs text-apple-ink focus:outline-none focus:border-apple-primary focus:bg-apple-canvas transition-colors"
            />
          </div>
        </div>
      </div>

      {/* 模块 3：输出与系统桌面特性 */}
      <div className="bg-apple-canvas rounded-apple-lg border border-apple-hairline p-6 shadow-sm">
        <div className="flex items-center space-x-2.5 pb-4 mb-4 border-b border-apple-hairline">
          <div className="w-8 h-8 rounded-apple-sm bg-apple-parchment flex items-center justify-center text-apple-primary">
            <Folder className="w-4 h-4" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-apple-ink tracking-apple-headline">
              输出与桌面系统特性
            </h2>
            <p className="text-xs text-apple-ink-muted-48">
              自定义译本输出形式与系统级休眠/通知联动
            </p>
          </div>
        </div>

        <div className="space-y-4">
          {/* 单语与双语开关 */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <label className="p-3.5 bg-apple-parchment/40 rounded-apple-md border border-apple-hairline flex items-center justify-between cursor-pointer hover:bg-apple-parchment transition-colors">
              <div>
                <span className="text-xs font-semibold text-apple-ink block">
                  生成纯中文单语译本 (.zh.epub)
                </span>
                <span className="text-[11px] text-apple-ink-muted-48">
                  仅保留高质量中文翻译文本
                </span>
              </div>
              <input
                type="checkbox"
                checked={formData.output.mono}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    output: { ...formData.output, mono: e.target.checked },
                  })
                }
                className="w-4 h-4 text-apple-primary rounded accent-apple-primary"
              />
            </label>

            <label className="p-3.5 bg-apple-parchment/40 rounded-apple-md border border-apple-hairline flex items-center justify-between cursor-pointer hover:bg-apple-parchment transition-colors">
              <div>
                <span className="text-xs font-semibold text-apple-ink block">
                  生成中英双语对照本 (.bilingual.epub)
                </span>
                <span className="text-[11px] text-apple-ink-muted-48">
                  段落级中英文对照排版
                </span>
              </div>
              <input
                type="checkbox"
                checked={formData.output.bilingual}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    output: { ...formData.output, bilingual: e.target.checked },
                  })
                }
                className="w-4 h-4 text-apple-primary rounded accent-apple-primary"
              />
            </label>
          </div>

          {/* 系统特性开关 */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2">
            <label className="p-3.5 bg-apple-parchment/40 rounded-apple-md border border-apple-hairline flex items-center justify-between cursor-pointer hover:bg-apple-parchment transition-colors">
              <div className="flex items-center space-x-2">
                <Moon className="w-4 h-4 text-apple-primary" />
                <div>
                  <span className="text-xs font-semibold text-apple-ink block">
                    翻译期间阻止系统休眠
                  </span>
                  <span className="text-[11px] text-apple-ink-muted-48">
                    长时间运行防中断 (macOS/Windows)
                  </span>
                </div>
              </div>
              <input
                type="checkbox"
                checked={formData.preferences.prevent_sleep}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    preferences: {
                      ...formData.preferences,
                      prevent_sleep: e.target.checked,
                    },
                  })
                }
                className="w-4 h-4 text-apple-primary rounded accent-apple-primary"
              />
            </label>

            <label className="p-3.5 bg-apple-parchment/40 rounded-apple-md border border-apple-hairline flex items-center justify-between cursor-pointer hover:bg-apple-parchment transition-colors">
              <div className="flex items-center space-x-2">
                <Bell className="w-4 h-4 text-apple-primary" />
                <div>
                  <span className="text-xs font-semibold text-apple-ink block">
                    完成时发送系统原生通知
                  </span>
                  <span className="text-[11px] text-apple-ink-muted-48">
                    任务结束或出错时弹出 Toast
                  </span>
                </div>
              </div>
              <input
                type="checkbox"
                checked={formData.preferences.enable_notifications}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    preferences: {
                      ...formData.preferences,
                      enable_notifications: e.target.checked,
                    },
                  })
                }
                className="w-4 h-4 text-apple-primary rounded accent-apple-primary"
              />
            </label>
          </div>
        </div>
      </div>

      {/* 底部保存按钮 */}
      <div className="flex items-center justify-end space-x-3 pt-2">
        {saveSuccess && (
          <span className="text-xs font-medium text-emerald-600 flex items-center space-x-1 animate-fade-in">
            <CheckCircle2 className="w-3.5 h-3.5" />
            <span>配置已成功保存至 config.yaml</span>
          </span>
        )}

        <button
          type="submit"
          disabled={isSaving}
          className="px-8 py-2.5 rounded-apple-pill bg-apple-primary hover:bg-apple-primary-focus text-white text-sm font-semibold shadow-sm hover:shadow transition-all duration-150 flex items-center space-x-2 disabled:opacity-50"
        >
          <Save className="w-4 h-4" />
          <span>{isSaving ? "正在保存..." : "保存设置"}</span>
        </button>
      </div>
    </form>
  );
};
