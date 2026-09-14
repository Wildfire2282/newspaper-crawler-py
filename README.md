# 报刊下载器

批量下载**人民日报、光明日报、经济日报、大众日报**电子版：按日期范围抓取当日全部版面与文章，
输出 Markdown 或纯文本。是 [newspaper-crawler](https://github.com/Wildfire2282/newspaper-crawler)
（Tauri + Rust 桌面版）的纯 Python 重构。

## 安装

需要 [uv](https://docs.astral.sh/uv/)；Python 3.12+ 由 uv 按 `.python-version` 自动准备。

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # 安装 uv
uv sync                                           # 安装项目与 dev 依赖
```

用 `uv run` 前缀执行命令，无需手动激活 `.venv`。

## 使用

```bash
# 交互式菜单（无参数且处于终端）
uv run newspaper-crawler

# 非交互：列出站点 / 预演 / 下载
uv run newspaper-crawler sites --json
uv run newspaper-crawler plan  --sites rmrb --start 2026-09-01 --end 2026-09-03
uv run newspaper-crawler crawl --sites rmrb,gmrb --start 2026-09-01 --end 2026-09-03
```

`crawl` 参数：`--sites`（ID / 名称 / 别名，逗号分隔，默认 `all`）、`--start` / `--end`
（`YYYY-MM-DD` 或 `YYYYMMDD`，默认最近 7 天）、`-o` 输出目录（默认 `<项目目录>/downloads`）、
`-f md|txt`、`--workers`、`--fast`、`--skip-existing` / `--no-skip-existing`、`--json`、
`-q`、`-v`。完整说明见 `--help`。

结果写 stdout，进度写 stderr；`--json` 输出单个 JSON 对象。`Ctrl+C` 可中断，已写入的文件保留，
下次运行自动续传。

退出码：`0` 成功（含当日无报纸）、`1` 运行期错误、`2` 用法或参数错误、`130` 被中断。

## 支持站点

| 站点 | ID | 别名 |
|------|-----|------|
| 人民日报 | `rmrb` | 人民 / renmin / people |
| 光明日报 | `gmrb` | 光明 / guangming |
| 经济日报 | `jjrb` | 经济 / jingji |
| 大众日报 | `dzrb` | 大众 / dazhong |

输出路径：`<输出目录>/<站点>/<年>/<月>/<YYYY-MM-DD>.md`。

## 开发

```bash
uv run ruff check . && uv run mypy newspaper_crawler && uv run pytest
```

CI 在 Python 3.12 / 3.13 / 3.14 上运行上述检查与 `uv build`。

## 许可证

[MIT](LICENSE)。仅供个人学习与技术交流，请尊重各报纸版权，勿用于商业用途或公开传播。
