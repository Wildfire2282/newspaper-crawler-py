# 报刊下载器（Python 交互式命令行版）

通过命令行交互式批量下载**人民日报、光明日报、经济日报、大众日报**电子版。

本仓库是 [Wildfire2282/newspaper-crawler](https://github.com/Wildfire2282/newspaper-crawler)
（Tauri + Rust 桌面版）的纯 Python 重构，核心抓取逻辑与 Rust 版保持一致。

## 功能特点

- **多站点支持**：人民日报、光明日报、经济日报、大众日报
- **批量下载**：按日期范围自动抓取所有版面
- **并发抓取**：多线程并行下载，提高效率
- **断点续传**：已下载的日期文件自动跳过
- **多格式输出**：支持 Markdown 与纯文本
- **快速模式**：降低请求延迟、加大并发，加快下载速度
- **交互式菜单**：基于 `rich` 的富终端界面，逐步引导配置
- **非交互子命令**：`crawl` / `sites` / `plan`，支持 `--json` 输出与稳定退出码，便于脚本与 AI agent 调用
- **工程化**：uv + `pyproject.toml` + `uv.lock` 管理依赖与环境，pytest 测试，ruff + mypy 检查，GitHub Actions CI

## 环境要求

- Python 3.12+（用 [uv](https://docs.astral.sh/uv/) 时无需自己装，`uv sync` 会按 `.python-version` 准备）
- [uv](https://docs.astral.sh/uv/)（推荐的依赖与环境管理工具）

## 安装

```bash
# 1. 安装 uv（若尚未安装）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. 按 uv.lock 精确复现 .venv 并安装项目 + dev 依赖
uv sync

# 只装运行期依赖（不带 pytest/ruff/mypy）
uv sync --no-dev
```

`uv sync` 会创建/更新 `.venv`，无需手动 `activate`——用 `uv run` 执行即可，它会自动使用该环境：

```bash
uv run python crawler.py
uv run newspaper-crawler sites --json
```

<details>
<summary>不使用 uv 时的等价做法</summary>

```bash
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

pip install -e .               # 运行期依赖
pip install --group dev -e .   # 额外安装 dev 依赖组（需 pip 25.1+）

# 需要传统 requirements.txt 时（例如部署到无 uv 的环境）
uv export --no-dev --format requirements-txt > requirements.txt
```

</details>

## 使用

入口有三种，等价可用：

```bash
uv run python crawler.py                 # 无参数 + 终端 → 交互式菜单
uv run python -m newspaper_crawler       # 模块入口
uv run newspaper-crawler                 # 已安装的命令行入口

# 查看帮助 / 版本
uv run python crawler.py --help
uv run python crawler.py --version
```

> 已 `source .venv/bin/activate` 后，直接写 `python crawler.py` 亦可。

### 交互式流程

1. **选择报纸**：输入站点编号（逗号/空格分隔，`all` 全选），默认全选
2. **设置日期范围**：支持 `YYYY-MM-DD` 或 `YYYYMMDD`，默认最近 7 天
3. **设置输出目录**：默认 `./downloads`（相对项目位置），支持 `~` 展开
4. **设置输出格式**：`md` / `txt`
5. **高级选项**：并发线程数（默认 5）、快速模式、断点续传
6. **开始下载**：确认配置后开始，实时显示每日进度日志
7. **退出**

下载过程中按 `Ctrl+C` 可中断：已按日原子写入的文件全部保留，未完成的日期在下次运行
（开启断点续传）时自动继续。

### 非交互 / Agent 用法

带子命令即进入非交互模式，**永不弹出确认提示**，适合脚本与 AI agent 调用。

```bash
# 列出可用站点（自描述，便于 agent 发现）
python crawler.py sites [--json]

# 预演：列出将抓取/跳过的日期与目标路径（不联网、不写盘）
python crawler.py plan --sites rmrb --start 2026-09-01 --end 2026-09-03 --json

# 执行下载
python crawler.py crawl --sites rmrb,gmrb --start 2026-09-01 --end 2026-09-03 \
  --output-dir ./downloads --format md --workers 5
```

`crawl` 常用参数：

| 参数 | 说明 |
|------|------|
| `--sites` | 站点 id/名称/别名，逗号分隔；默认 `all` |
| `--start` / `--end` | 日期范围，支持 `YYYY-MM-DD` 或 `YYYYMMDD`；默认最近 7 天 |
| `-o, --output-dir` | 输出目录；默认 `./downloads` |
| `-f, --format` | `md`（默认）或 `txt` |
| `--workers` | 并发线程数；默认 5 |
| `--fast` | 快速模式：降低延迟并把并发提升到至少 10 |
| `--skip-existing` / `--no-skip-existing` | 是否跳过已下载日期；默认跳过 |
| `--json` | 结果以 JSON 输出到 stdout |
| `-q, --quiet` | 不输出进度 |
| `-v, --verbose` | 输出调试日志 |

**输出约定**：结果写 **stdout**，进度与日志写 **stderr**。`--json` 时 stdout 是单个 JSON 对象，
可直接管道给 `python -m json.tool` 或 `jq`。

**退出码**：

| 码 | 含义 |
|----|------|
| 0 | 成功（含“当日无报纸”这类正常空结果） |
| 1 | 运行期错误（抓取失败、站点名无法识别等，细节见 JSON 的 `errors` / `unknown_sites`） |
| 2 | 用法或参数错误 |
| 130 | 被 `Ctrl+C` 中断 |

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
    "days_attempted": 1, "days_success": 1, "days_skipped": 0, "days_empty": 0,
    "total_editions": 20, "total_articles": 121, "total_errors": 0
  },
  "files": ["/path/to/downloads/人民日报/2026/09/2026-09-10.md"],
  "skipped": [],
  "errors": []
}
```

> 无参数且 stdin/stdout 都不是终端时，会直接报用法错误（退出码 2），而不是默认执行全量下载。
> 需要在管道中显式进入菜单时，用 `python crawler.py interactive`。

## 开发

```bash
uv sync                        # 安装项目 + dev 依赖组

uv run ruff check .            # 静态检查
uv run ruff format .           # 格式化
uv run mypy newspaper_crawler  # 类型检查
uv run pytest                  # 运行测试（默认带覆盖率报告）
```

## 支持站点

| 站点 | ID | 说明 |
|------|-----|------|
| 人民日报 | `rmrb` | 2024-12-01 新旧系统切换（自动识别） |
| 光明日报 | `gmrb` | 2026-01-01 新旧系统切换（自动识别） |
| 经济日报 | `jjrb` | 标准版面 + 文章结构 |
| 大众日报 | `dzrb` | 索引页一次性获取 |

## 输出目录结构

```
<输出目录>/
├── 人民日报/
│   └── 2025/
│       └── 06/
│           └── 2025-06-01.md        # 当日全部版面与文章
├── 光明日报/
│   └── 2025/
│       └── 06/
│           └── 2025-06-01.md
└── ...
```

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
│   ├── models.py               # 数据模型（文章/版面/统计/配置）
│   ├── http.py                 # HTTP 客户端（重试/退避/GBK 回退）
│   ├── base.py                 # 站点爬虫基类与并发抓取
│   ├── scheduler.py            # 调度器（逐日爬取/跳过/写文件）
│   ├── formatter.py            # Markdown / 纯文本格式化
│   ├── registry.py             # 站点注册表
│   ├── storage.py              # 原子写入
│   ├── util.py                 # 公共工具（日期解析/选项构造/日志）
│   └── sites/                  # 各站点实现
│       ├── rmrb.py             # 人民日报
│       ├── gmrb.py             # 光明日报
│       ├── jjrb.py             # 经济日报
│       └── dzrb.py             # 大众日报
```

## 与 Rust/Tauri 版差异

- 界面由桌面 GUI 改为命令行：交互式菜单 + 面向脚本/agent 的非交互子命令
- 后端由 Rust（reqwest + scraper）改为 Python（requests + BeautifulSoup4）
- 抓取逻辑（版面/文章解析、新旧系统切换日期、重试与编码回退）与原版保持一致
- 移除了系统托盘、桌面通知等桌面端专属功能

## 许可证

[MIT](LICENSE)

## 免责声明

本项目仅供个人学习与技术交流使用。请尊重各报纸版权，下载内容请勿用于商业用途或公开传播。
各站点页面结构可能随时调整，若解析失效请提交 Issue。
