# Wenyi

**English** | [简体中文](docs/zh/README.md)

![Wenyi bilingual EPUB preview](docs/images/bilingual-preview.png)

Wenyi is a command-line tool for translating EPUB, FB2, TXT, Markdown, HTML, and PDF novels from multiple languages into Chinese. It focuses on long-form translation quality through whole-book analysis, rolling context, an evolving glossary, polishing, and review stages.

## Quick start

Wenyi requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
export DEEPSEEK_API_KEY=sk-...
uv run trans-novel translate book.epub
```

## Cross-platform Web UI

Wenyi also ships a lightweight local single-user web workbench that reuses the same Python translation engine on macOS, Linux, and Windows. It only listens on the loopback address and does not serve remote accounts or multiple users; do not deploy it as a public service.

After installing the wheel, start it directly:

```bash
trans-novel-web
```

From source, run `uv run trans-novel-web`, or use the launcher scripts that sync dependencies and open the browser for you.

macOS / Linux:

```bash
./script/start-webui.sh
```

Windows:

```bat
script\start-webui.bat
```

The Web UI defaults to `http://127.0.0.1:8787`; if that port is busy, the next available port is chosen. The launcher also opens the default browser.

Model configuration supports DeepSeek, OpenAI, OpenRouter, OpenAI-compatible endpoints, Ollama, and vLLM. The three model tiers, API base URL, and API key can be managed in the Web UI's Model Configuration panel; compatible endpoints can additionally choose between DeepSeek, OpenAI, OpenRouter, or no thinking-parameter protocol conversion.

Each translation task has its own configuration snapshot and state directory. The workbench lets you inspect and manage glossary terms and conflicts, the whole-book style profile, per-chapter source and target text, review issues, and manual revisions; after edits you can re-export monolingual or bilingual EPUB/TXT. Task details also expose persistent event logs and token usage statistics, broken down by model tier, pipeline stage, and cache hit rate.

Frontend development:

```bash
cd web
npm install
npm run dev
```

The release static assets are bundled into the wheel, so ordinary users do not need Node to start the Web UI. The source repository keeps `web/dist` for local runs; run `npm run build` after frontend changes to refresh it.

The Web UI stores books, task state, and internal artifacts under `~/.wenyi-webui` by default; finished files can be downloaded from the workbench. All data lives in local files and task-scoped state—no database, Redis, or container services required.

By default, Wenyi writes a monolingual Chinese EPUB to the source file's `output/` directory as `book.zh.epub`. A bilingual source-and-translation edition can be enabled when needed. Runtime state, chapter JSON files, the glossary database, and reports are stored under `state/`. To continue an interrupted run, execute the same `translate` command again:

```bash
uv run trans-novel translate book.epub
uv run trans-novel status book.epub
```

To inspect the generated style guide and initial glossary before translating the body text, prepare the book first:

```bash
uv run trans-novel prepare book.epub
uv run trans-novel translate book.epub
```

Final review is disabled by default. Set `pipeline.review: true` to run it
automatically after the complete book has been translated and the glossary has
reached its final state, or run and repeat the stage independently:

```bash
uv run trans-novel review book.epub
uv run trans-novel review book.epub --force --fix
```

## Supported formats and output

- Input: EPUB, FB2, TXT, Markdown, HTML, and PDF.
- Output: monolingual EPUB by default, optional bilingual EPUB, or TXT, HTML, and Markdown exports.
- PDF import: the first run uses MinerU and requires `MINERU_API_KEY`. The converted HTML is cached at `state/<book>/source/converted.html` and reused by later runs.
- EPUB preservation: Wenyi attempts to retain the original styles, images, table of contents, and anchors while converting translated content to horizontal layout.
- Language detection: the source language is detected automatically by default, or it can be fixed to an ISO language code in `config.yaml`.

Select output editions from the command line:

```bash
uv run trans-novel translate book.epub --bilingual           # monolingual and bilingual
uv run trans-novel translate book.epub --no-mono --bilingual # bilingual only
```

The bilingual edition places the translation before the source text by default. Set `output.bilingual_order` to `source_first` in `config.yaml` to reverse the order.

## Documentation

- [Usage guide](docs/usage.md): installation, Windows setup, input/output, resumability, and independent workflow stages.
- [Configuration](docs/configuration.md): providers, languages, pipeline switches, segmentation, and paths.
- [Translation pipeline](docs/pipeline.md): whole-book analysis, terminology, context, polishing, review, and resumability.
- [Contributing](CONTRIBUTING.md): development, testing, and contribution guidelines.

Translated state directories for public-domain books may be shared through [wenyi-bookcase](https://github.com/BigDawnGhost/wenyi-bookcase). Do not publish copyrighted text, private books, or `state/` directories containing sensitive information without permission.

## Project status

Wenyi is an early-stage personal project focused on making long-form machine translation more accurate, consistent, and readable. Reports of inconsistent names, recurring expressions, omissions, formatting problems, and provider compatibility issues are welcome through GitHub Issues and Discussions. Pull requests are also appreciated.

Community:

- [Join the Wenyi Discord server](https://discord.gg/Tybfva4HT)
- QQ group: 1055065098

## Star history

<a href="https://www.star-history.com/?repos=BigDawnGhost%2FWenyi&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=BigDawnGhost/Wenyi&type=date&theme=dark&legend=top-left&sealed_token=VFuKZdjDh-9e2mG4qlvqeSpCkWCoRf9ZRy0hIDLdaECFQeoNNlQ20QxSD4PuvTZp1RJg7J2s5hr57Eq66paMrhikuuI3kc41uZZCYb-bTqsUafeSB7AVdhw7bmz70NhkVXABHtSIHdw0DROZaInmznYJ651gP2klEeW8OOM8EkfJnXgDld6f0xn8mIJ9" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=BigDawnGhost/Wenyi&type=date&legend=top-left&sealed_token=VFuKZdjDh-9e2mG4qlvqeSpCkWCoRf9ZRy0hIDLdaECFQeoNNlQ20QxSD4PuvTZp1RJg7J2s5hr57Eq66paMrhikuuI3kc41uZZCYb-bTqsUafeSB7AVdhw7bmz70NhkVXABHtSIHdw0DROZaInmznYJ651gP2klEeW8OOM8EkfJnXgDld6f0xn8mIJ9" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=BigDawnGhost/Wenyi&type=date&legend=top-left&sealed_token=VFuKZdjDh-9e2mG4qlvqeSpCkWCoRf9ZRy0hIDLdaECFQeoNNlQ20QxSD4PuvTZp1RJg7J2s5hr57Eq66paMrhikuuI3kc41uZZCYb-bTqsUafeSB7AVdhw7bmz70NhkVXABHtSIHdw0DROZaInmznYJ651gP2klEeW8OOM8EkfJnXgDld6f0xn8mIJ9" />
 </picture>
</a>
