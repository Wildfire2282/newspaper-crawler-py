#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""报刊下载器入口。

用法：
    python crawler.py              无参数且处于终端时进入交互式菜单
    python crawler.py --help       查看全部子命令、参数、示例与退出码
    python crawler.py sites        列出可用站点
    python crawler.py plan ...     预演将抓取/跳过的日期（不联网、不写盘）
    python crawler.py crawl ...    执行下载

完整说明由 `--help` 自描述；实现在 newspaper_crawler.cli。
"""

import sys

from newspaper_crawler.cli import main

if __name__ == "__main__":
    sys.exit(main())
