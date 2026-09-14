#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""报刊下载器入口（兼容 shim）。

真正的实现位于 newspaper_crawler 包内：

    python crawler.py                 # 终端下进入交互式菜单
    python crawler.py crawl --help    # 非交互子命令
    python -m newspaper_crawler       # 等价入口
"""

import sys

from newspaper_crawler.cli import main

if __name__ == "__main__":
    sys.exit(main())
