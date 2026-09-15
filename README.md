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

`--help` 即完整文档：`crawl` / `plan` / `sites` / `runs` 的参数说明、可直接复制的示例、
JSON 输出字段与退出码都在其中。命令以 `--json` 输出机器可读结果（stdout），进度写 stderr，
适合脚本与 AI agent 调用。

## 状态持久化

当前目录下的 `.newspaper-crawler.json` 保存偏好与运行账本（可用环境变量 `CRAWLER_STATE`
指向别处），写入是原子的（临时文件 + `os.replace`）：

- **偏好**：交互式菜单或命令行用过的站点、日期、输出目录、格式、并发等，下次直接沿用；
  显式传入的参数优先。
- **账本**：最近一次运行的每个「站点 × 日期」状态（`done` / `skipped` / `empty` /
  `failed` / `pending`）与最近 20 次运行摘要。

中断或失败后可直接续跑：

```bash
uv run newspaper-crawler runs            # 查看历史与未完成的日期
uv run newspaper-crawler plan --resume   # 预演将续抓哪些日期（不联网、不写盘）
uv run newspaper-crawler crawl --resume  # 只重跑 pending / failed 的日期
```

## 开发

```bash
uv run ruff check . && uv run mypy newspaper_crawler && uv run pytest
```

## 许可证

[MIT](LICENSE)
