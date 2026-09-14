# 报刊下载器

批量下载**人民日报、光明日报、经济日报、大众日报**电子版：按日期范围抓取当日全部版面与文章，
输出 Markdown 或纯文本。是 [newspaper-crawler](https://github.com/Wildfire2282/newspaper-crawler)
（Tauri + Rust 桌面版）的纯 Python 重构。

## 安装

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # 需要 uv
uv sync                                           # Python 3.12+ 由 uv 自动准备
```

## 用法

```bash
uv run newspaper-crawler           # 交互式菜单
uv run newspaper-crawler --help    # 全部子命令、参数、示例与退出码
```

`--help` 即完整文档：`crawl` / `sites` / `plan` 的参数说明、可直接复制的示例、
JSON 输出字段与退出码都在其中。命令以 `--json` 输出机器可读结果（stdout），进度写 stderr，
适合脚本与 AI agent 调用。

## 开发

```bash
uv run ruff check . && uv run mypy newspaper_crawler && uv run pytest
```

## 许可证

[MIT](LICENSE)
