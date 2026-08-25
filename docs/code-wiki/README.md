# 文译（Wenyi）Code Wiki

本 Wiki 是面向开发者的代码级文档，系统说明文译项目的整体架构、模块职责、关键类与函数、依赖关系以及运行方式。

面向使用者的安装/配置/翻译流程文档请见上级目录的 [`usage.md`](../usage.md)、[`configuration.md`](../configuration.md)、[`pipeline.md`](../pipeline.md)。

## 文档索引

| 文档 | 内容 |
|------|------|
| [01-architecture.md](01-architecture.md) | 项目整体架构、模块依赖关系、翻译数据流 |
| [02-config.md](02-config.md) | 配置系统：`config.yaml`、`Config` 模型与默认值 |
| [03-ingest.md](03-ingest.md) | 输入解析与切分：EPUB / FB2 / TXT 解析器与批次切分 |
| [04-llm.md](04-llm.md) | LLM Provider 抽象层：多服务商接入、档位、用量跟踪 |
| [05-agents.md](05-agents.md) | 翻译 Agent 体系：分析、翻译、审校、润色、一致性 QA |
| [06-glossary.md](06-glossary.md) | 术语库与翻译记忆：SQLite 持久化、冲突裁决 |
| [07-pipeline.md](07-pipeline.md) | 流水线编排与状态机：断点续跑、滚动上下文 |
| [08-assemble.md](08-assemble.md) | 回填组装与后处理：EPUB/TXT 生成、标点规范化 |
| [09-cli.md](09-cli.md) | 命令行接口：`translate` / `resume` / `status` / `tools` |
| [10-webui.md](10-webui.md) | Web UI 后端 API 与前端结构 |
| [11-running.md](11-running.md) | 项目运行与开发指南：环境、运行、构建、调试 |
| [12-testing.md](12-testing.md) | 测试体系：单元测试与 Fake LLM |

## 项目概览

**文译**是一个多 Agent 协同的长篇小说翻译系统，将多语言 EPUB / FB2 / TXT 小说翻译为中文。其设计重点不是"快速翻译"，而是**长篇小说的翻译质量**：全书预扫、滚动上下文、实时术语库、章末审校、严重项定向重译、跨章一致性 QA、断点续跑。

- **语言**：Python 3.10+（后端）+ TypeScript/React 19（Web UI 前端）
- **包管理**：[uv](https://docs.astral.sh/uv/)（后端）、npm（前端）
- **核心依赖**：`openai`、`pydantic` v2、`typer`、`rich`、`fastapi`、`uvicorn`、`ebooklib`、`beautifulsoup4`、`lxml`、`tenacity`
- **入口**：`trans-novel`（CLI）、`trans-novel-web`（Web UI 服务器）
- **版本**：0.2.0

## 快速导航

- 想了解整体设计 → [01-architecture.md](01-architecture.md)
- 想运行项目 → [11-running.md](11-running.md)
- 想理解翻译流水线 → [07-pipeline.md](07-pipeline.md) + [05-agents.md](05-agents.md)
- 想接入新的 LLM 服务商 → [04-llm.md](04-llm.md)
- 想支持新的输入格式 → [03-ingest.md](03-ingest.md)
- 想了解 Web UI → [10-webui.md](10-webui.md)
