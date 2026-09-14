# 报刊下载器（Python 版）

批量下载**人民日报、光明日报、经济日报、大众日报**电子版：按日期范围逐日抓取当日全部版面与文章，
输出 Markdown 或纯文本。提供交互式菜单与面向脚本 / AI agent 的非交互子命令两种使用方式。

本仓库是 [Wildfire2282/newspaper-crawler](https://github.com/Wildfire2282/newspaper-crawler)
（Tauri + Rust 桌面版）的纯 Python 重构，抓取逻辑与原版保持一致。

## 功能

- **批量下载**：按日期范围逐日抓取全部版面与正文
- **并发抓取**：多线程并行，可调整并发数并启用快速模式
- **断点续传**：已下载日期自动跳过；中断后已写入的文件保留
- **多格式输出**：Markdown / 纯文本，按「站点 / 年 / 月 / 日期」组织
- **双模式入口**：交互式菜单，或 `crawl` / `sites` / `plan` 子命令（支持 `--json` 与稳定退出码）

## 环境要求

- [uv](https://docs.astral.sh/uv/)：依赖与环境管理
- Python 3.12+：由 uv 按 `.python-version` 自动准备，无需手动安装

## 安装

```bash
# 安装 uv（若尚未安装）
curl -LsSf https://astral.sh/uv/install.sh | sh

uv sync            # 按 uv.lock 复现 .venv，安装项目与 dev 依赖
uv sync --no-dev   # 仅安装运行期依赖
```

`uv sync` 会创建并维护 `.venv`，无需手动激活：使用 `uv run` 执行即可自动使用该环境。

<details>
<summary>不使用 uv 的等价做法</summary>

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .                 # 运行期依赖
pip install --group dev -e .     # 追加 dev 依赖组（需 pip 25.1+）

# 导出传统 requirements.txt，供无 uv 的部署环境使用
uv export --no-dev --format requirements-txt > requirements.txt
```

</details>

## 使用

三种入口等价：

```bash
uv run newspaper-crawler          # 已安装的命令行入口
uv run python crawler.py          # 仓库根目录的兼容入口
uv run python -m newspaper_crawler
```

下文示例统一使用 `uv run newspaper-crawler`；已激活 `.venv` 后可省略 `uv run`。

### 交互式模式

无参数且处于终端时进入交互式菜单，依次配置站点、日期范围、输出目录、输出格式与高级选项，
确认后开始下载并实时输出每日进度。

下载过程中按 `Ctrl+C` 可中断。文件按日原子写入，已完成的日期保留，未完成的日期在下次运行
（开启断点续传）时自动继续。

### 非交互模式（脚本 / AI agent）

指定子命令即进入非交互模式，不会出现任何确认提示。

```bash
# 列出可用站点
uv run newspaper-crawler sites [--json]

# 预演：列出将抓取 / 跳过的日期与目标路径（不联网、不写盘）
uv run newspaper-crawler plan --sites rmrb --start 2026-09-01 --end 2026-09-03 --json

# 下载
uv run newspaper-crawler crawl --sites rmrb,gmrb --start 2026-09-01 --end 2026-09-03 \
  --output-dir ./downloads --format md --workers 5
```

`crawl` 参数：

| 参数 | 说明 |
|------|------|
| `--sites` | 站点 ID、名称或别名，逗号分隔；默认 `all`（全部站点） |
| `--start` / `--end` | 日期范围，支持 `YYYY-MM-DD` 或 `YYYYMMDD`；默认最近 7 天 |
| `-o, --output-dir` | 输出目录；默认 `<项目目录>/downloads`，显式相对路径相对当前工作目录 |
| `-f, --format` | 输出格式：`md`（默认）或 `txt` |
| `--workers` | 并发线程数；默认 5 |
| `--fast` | 快速模式：缩短请求间隔，并发不低于 10 |
| `--skip-existing` / `--no-skip-existing` | 是否跳过已下载日期；默认跳过 |
| `--json` | 结果以 JSON 写入 stdout |
| `-q, --quiet` | 不输出进度 |
| `-v, --verbose` | 输出调试日志（含 HTTP 重试细节） |
| `-y, --yes` | 兼容占位；非交互模式本就不会询问 |

`sites` 仅接受 `--json`；`plan` 接受相同的 `--sites` / `--start` / `--end` / `-o` / `-f` / `--json`。

**输出约定**：结果写入 stdout，进度与日志写入 stderr。`--json` 时 stdout 为单个 JSON 对象，
可直接交给 `jq` 或 `python -m json.tool`。

**退出码**：

| 码 | 含义 |
|----|------|
| 0 | 成功（含「当日无报纸」这类正常空结果） |
| 1 | 运行期错误（抓取失败、站点无法识别等；细节见 JSON 的 `errors` 与 `unknown_sites`） |
| 2 | 用法或参数错误 |
| 130 | 被 `Ctrl+C` 中断 |

> 无参数且 stdin / stdout 均非终端时，直接报用法错误（退出码 2），不会默认执行全量下载。
> 需在管道场景下显式进入交互菜单时，使用 `interactive` 子命令。

`crawl --json` 输出示例：

```json
{
  "ok": true,
  "sites": ["rmrb"],
  "unknown_sites": [],
  "start_date": "2026-09-10",
  "end_date": "2026-09-10",
  "output_dir": "/path/to/downloads",
  "format": "md",
  "elapsed_secs": 3.0,
  "stats": {
    "days_attempted": 1,
    "days_success": 1,
    "days_skipped": 0,
    "days_empty": 0,
    "total_editions": 20,
    "total_articles": 121,
    "total_errors": 0
  },
  "files": ["/path/to/downloads/人民日报/2026/09/2026-09-10.md"],
  "skipped": [],
  "errors": []
}
```

## 支持站点

| 站点 | ID | 别名 | 说明 |
|------|-----|------|------|
| 人民日报 | `rmrb` | 人民 / renmin / people | 2024-12-01 新旧系统切换（自动识别） |
| 光明日报 | `gmrb` | 光明 / guangming | 2026-01-01 新旧系统切换（自动识别） |
| 经济日报 | `jjrb` | 经济 / jingji | 标准版面 + 文章结构 |
| 大众日报 | `dzrb` | 大众 / dazhong | 索引页一次性获取 |

## 输出目录结构

```
<输出目录>/
└── 人民日报/
    └── 2026/
        └── 09/
            └── 2026-09-10.md    # 当日全部版面与文章
```

以上以 Markdown 为例；`--format txt` 时文件扩展名为 `.txt`。

## 开发

```bash
uv sync                        # 安装项目与 dev 依赖

uv run ruff check .            # 静态检查
uv run ruff format .           # 格式化
uv run mypy newspaper_crawler  # 类型检查
uv run pytest                  # 运行测试（默认输出覆盖率报告）
```

CI（`.github/workflows/ci.yml`）在 Python 3.12 / 3.13 / 3.14 上执行上述检查与 `uv build`；
Dependabot 每周更新依赖与 Actions 版本。

## 项目结构

```
newspaper-crawler-py/
├── crawler.py                  # 兼容入口 shim → newspaper_crawler.cli
├── pyproject.toml              # 打包元数据 / 依赖 / ruff / mypy / pytest 配置
├── uv.lock                     # 锁定依赖版本，保证可复现
├── .python-version             # 固定项目 Python（3.12）
├── LICENSE                     # MIT
├── tests/                      # pytest 测试
├── .github/
│   ├── workflows/ci.yml        # CI：ruff + mypy + pytest + build
│   └── dependabot.yml          # 依赖与 Actions 版本自动更新
├── newspaper_crawler/          # 核心库
│   ├── cli.py                  # 非交互子命令（crawl / sites / plan）
│   ├── tui.py                  # 交互式菜单（rich）
│   ├── __main__.py             # python -m newspaper_crawler 入口
│   ├── models.py               # 数据模型（文章 / 版面 / 统计 / 配置）
│   ├── http.py                 # HTTP 客户端（重试 / 退避 / GBK 回退）
│   ├── base.py                 # 站点爬虫基类与并发抓取
│   ├── scheduler.py            # 调度器（逐日爬取 / 跳过 / 写文件）
│   ├── formatter.py            # Markdown / 纯文本格式化
│   ├── registry.py             # 站点注册表
│   ├── storage.py              # 原子写入
│   ├── util.py                 # 公共工具（日期解析 / 选项构造 / 日志）
│   └── sites/                  # 各站点实现
│       ├── rmrb.py             # 人民日报
│       ├── gmrb.py             # 光明日报
│       ├── jjrb.py             # 经济日报
│       └── dzrb.py             # 大众日报
```

## 与 Rust / Tauri 版差异

- 界面：桌面 GUI → 命令行（交互式菜单 + 非交互子命令）
- 后端：Rust（reqwest + scraper）→ Python（requests + BeautifulSoup4）
- 保持一致：版面与文章解析、新旧系统切换日期、重试与编码回退
- 已移除：系统托盘、桌面通知等桌面端专属功能

## 许可证

[MIT](LICENSE)

## 免责声明

本项目仅供个人学习与技术交流使用。请尊重各报纸版权，下载内容请勿用于商业用途或公开传播。
各站点页面结构可能调整，若解析失效请提交 Issue。
