# 文译 macOS 原生 App

- [x] 为 Python worker 编写协议测试并实现 JSON Lines 入口
- [x] 扩展流水线阶段进度与 UUID 状态目录支持
- [x] 创建 macOS 15 SwiftUI/Xcode 工程与构建脚本
- [x] 实现书架、书签、导入/重定位/删除和持久化
- [x] 实现本地 API 配置、权限、三档模型与翻译选项
- [x] 实现 Python 自动检测、依赖预检和手动选择
- [x] 实现无限制多任务进程管理、停止、续跑与事件解析
- [x] 实现主窗口、设置窗口、进度、产物和通知
- [x] 补齐 Swift/Python 测试并执行真实构建运行验证
- [x] 更新使用与分发文档
- [x] 安全暂停真实翻译任务并验证断点未回退
- [x] 修复正文阶段、详细进度显示和停止状态竞态
- [x] 补充断点进度读取与旧数据兼容测试
- [x] 增加跨暂停累计的翻译有效运行时间显示
- [x] 限制书架侧边栏宽度，防止挤占图书详情区域

## Review

- Python：`uv run python -m unittest discover -s tests -v`，113 项通过。
- Swift：`xcodebuild ... test CODE_SIGNING_ALLOWED=NO`，3 项通过。
- App：`./script/build_and_run.sh --verify` 构建并启动成功，进程验证通过。
- Bundle：最低系统版本为 macOS 15.0，内含 `trans_novel/app_worker.py`。
- Release：已提供 Developer ID、notarytool 和 DMG 脚本；因本机未提供签名身份与公证凭据，未执行真实公证。
- Python 3.14.6：真实创建临时 venv 并安装全部依赖成功，健康检查通过，环境约 86 MB。
- EPUB：导入时提取封面、书名、作者、语言、出版社、日期、标识符、简介、主题、章节数和文件大小。
- 工具栏：运行状态胶囊最小宽度设为 120pt，保持单行显示。
- 进度 UI：从真实断点恢复章节/段落进度，正文不再长期显示“准备图书”。
- 暂停验证：《玩乐关系》在 712/3775 段温和停止，worker 退出且断点无回退。

## Progress UI Review

- Swift：新增 3 项针对性断言，总计 6 项通过。
- Python：完整回归 114 项通过；Swift：6 项通过；Debug 构建与统一脚本启动验证成功。
- 启动验收：《玩乐关系》保持暂停，恢复 712/3775 段、4/16 章，未自动创建 worker。
- EPUB：旧书架记录已自动补录作者、26 个 spine 章节和 1,275,818 字节封面文件。
- 运行时间：从事件日志回填历史区间，暂停时间不计入；《玩乐关系》累计 3,249 秒（54分09秒）。
- 计时验证：Swift 9 项、Python 114 项通过；新版 App 启动后保持暂停且未创建 worker。
- 分栏布局：书架宽度限制为 180–280pt，默认 230pt。
