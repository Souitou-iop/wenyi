# 文译

将多语言 EPUB、FB2、TXT 小说翻译为简体中文的命令行工具。它以长篇小说的一致性为重点：全书预扫、滚动上下文、实时术语库、润色和审校均可按需启用。

## 快速开始

需要 Python 3.12+ 与 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync
export DEEPSEEK_API_KEY=sk-...
uv run trans-novel translate book.epub
```

翻译完成后，默认在源文件目录生成中文 EPUB；运行状态、章节 JSON、术语库和报告写入 `state/`。中断后可继续：

```bash
uv run trans-novel resume book.epub
uv run trans-novel status book.epub
```

## 支持范围

- 输入：EPUB、FB2、TXT。
- 输出：默认 EPUB；可通过 `--format txt` 导出纯文本。
- EPUB：尽量保留原书样式、图片、目录与锚点；译文元数据默认设为简体中文，并将竖排样式转为横排。
- 语言：默认由模型识别源语言，也可在 `config.yaml` 固定为语言代码。

## 文档

- [使用指南](docs/usage.md)：安装、Windows 使用、输入输出、续跑和工具命令。
- [配置说明](docs/configuration.md)：模型、源语言、流水线开关、切分与路径配置。
- [翻译流程](docs/pipeline.md)：预扫、术语、上下文、润色、审校和断点续跑如何协作。
- [贡献指南](CONTRIBUTING.md)：开发、测试和贡献要求。

公版书翻译生成的状态目录可在 [wenyi-bookcase](https://github.com/BigDawnGhost/wenyi-bookcase) 查看，也欢迎提交分享；请勿提交或分享无授权的版权文本、私人书籍或包含敏感信息的 `state/` 目录。

项目交流QQ群：1055065098

## 星标历史

<a href="https://www.star-history.com/?repos=BigDawnGhost%2FWenyi&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=BigDawnGhost/Wenyi&type=date&theme=dark&legend=top-left&sealed_token=VFuKZdjDh-9e2mG4qlvqeSpCkWCoRf9ZRy0hIDLdaECFQeoNNlQ20QxSD4PuvTZp1RJg7J2s5hr57Eq66paMrhikuuI3kc41uZZCYb-bTqsUafeSB7AVdhw7bmz70NhkVXABHtSIHdw0DROZaInmznYJ651gP2klEeW8OOM8EkfJnXgDld6f0xn8mIJ9" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=BigDawnGhost/Wenyi&type=date&legend=top-left&sealed_token=VFuKZdjDh-9e2mG4qlvqeSpCkWCoRf9ZRy0hIDLdaECFQeoNNlQ20QxSD4PuvTZp1RJg7J2s5hr57Eq66paMrhikuuI3kc41uZZCYb-bTqsUafeSB7AVdhw7bmz70NhkVXABHtSIHdw0DROZaInmznYJ651gP2klEeW8OOM8EkfJnXgDld6f0xn8mIJ9" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=BigDawnGhost/Wenyi&type=date&legend=top-left&sealed_token=VFuKZdjDh-9e2mG4qlvqeSpCkWCoRf9ZRy0hIDLdaECFQeoNNlQ20QxSD4PuvTZp1RJg7J2s5hr57Eq66paMrhikuuI3kc41uZZCYb-bTqsUafeSB7AVdhw7bmz70NhkVXABHtSIHdw0DROZaInmznYJ651gP2klEeW8OOM8EkfJnXgDld6f0xn8mIJ9" />
 </picture>
</a>
