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

## 环境要求

- Python 3.10+

## 安装

```bash
cd newspaper-crawler-py

# 创建虚拟环境（可选但推荐）
python3 -m venv .venv

# 激活虚拟环境
# Linux / macOS：
source .venv/bin/activate
# Windows：
.venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

> 仓库自带 `.venv/` 时可直接使用 `.venv/bin/python crawler.py`。

## 使用

```bash
# 进入交互式菜单
python crawler.py

# 查看帮助
python crawler.py --help

# 查看版本
python crawler.py --version
```

### 交互式流程

1. **选择报纸**：输入站点编号（逗号/空格分隔，`all` 全选），默认全选
2. **设置日期范围**：支持 `YYYY-MM-DD` 或 `YYYYMMDD`，默认最近 7 天
3. **设置输出目录**：默认 `./downloads`（相对脚本位置），支持 `~` 展开
4. **设置输出格式**：`md` / `txt`
5. **高级选项**：并发线程数（默认 5）、快速模式、断点续传
6. **开始下载**：确认配置后开始，实时显示每日进度日志
7. **退出**

下载过程中按 `Ctrl+C` 可中断：已按日原子写入的文件全部保留，未完成的日期在下次运行
（开启断点续传）时自动继续。

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
├── crawler.py                  # 入口：交互式命令行界面（rich）
├── requirements.txt            # 依赖清单
├── newspaper_crawler/          # 核心库
│   ├── models.py               # 数据模型（文章/版面/统计/配置）
│   ├── http.py                 # HTTP 客户端（重试/退避/GBK 回退）
│   ├── base.py                 # 站点爬虫基类与并发抓取
│   ├── scheduler.py            # 调度器（逐日爬取/跳过/写文件）
│   ├── formatter.py            # Markdown / 纯文本格式化
│   ├── registry.py             # 站点注册表
│   ├── storage.py              # 原子写入
│   ├── util.py                 # 公共工具
│   └── sites/                  # 各站点实现
│       ├── rmrb.py             # 人民日报
│       ├── gmrb.py             # 光明日报
│       ├── jjrb.py             # 经济日报
│       └── dzrb.py             # 大众日报
```

## 与 Rust/Tauri 版差异

- 界面由桌面 GUI 改为交互式命令行（`rich` 富终端）
- 后端由 Rust（reqwest + scraper）改为 Python（requests + BeautifulSoup4）
- 抓取逻辑（版面/文章解析、新旧系统切换日期、重试与编码回退）与原版保持一致
- 移除了系统托盘、桌面通知等桌面端专属功能

## 免责声明

本项目仅供个人学习与技术交流使用。请尊重各报纸版权，下载内容请勿用于商业用途或公开传播。
各站点页面结构可能随时调整，若解析失效请提交 Issue。
