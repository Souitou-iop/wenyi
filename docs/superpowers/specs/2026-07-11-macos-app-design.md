# 文译 macOS 原生 App 设计

## 产品形态

文译新增 macOS 15+ 原生 SwiftUI 客户端。主窗口采用书架与详情双栏布局，设置使用独立系统 Settings 窗口。App 引用用户原始 EPUB、FB2、TXT 文件，不复制图书；译文统一写入用户选择的输出目录。

每本图书由独立 Python 子进程执行现有 `trans_novel` 引擎。App 不设置图书级并发上限，也不创建等待队列。停止任务时先温和终止，超时后强制结束，并保留断点供继续翻译。

## Python 桥接

新增 JSON Lines worker。stdout 仅输出带协议版本、任务 ID 和时间戳的 `ready`、`phase`、`progress`、`completed`、`failed` 事件；stderr 保留诊断。每本书使用 UUID 隔离状态目录和临时 YAML。API Key 只通过子进程环境变量传入。

App 自动检测 Python 3.10+ 及项目依赖，也允许用户手动选择。App 不安装或修改第三方包，缺包时给出精确的 `python -m pip install` 命令。

## 配置与安全

API 设置沿用原项目的 strong、cheap、fast 三档模型结构。API Key 不使用 Keychain，而以明文保存在 `~/Library/Application Support/文译/settings.json`。目录权限为 0700、文件及临时文件权限为 0600，并采用原子替换。Key 不进入 UserDefaults、任务 YAML、日志、事件、通知或错误详情。

书架、任务状态和安全作用域书签保存在 Application Support。删除图书会移出书架并删除该书断点与中间状态，但不会删除原书或译文产物。

## 交付

首版为非沙盒 macOS App，使用 Developer ID 签名、公证和 DMG 分发，不面向 Mac App Store。项目提供统一的 `script/build_and_run.sh` 和 Codex Run 动作。
