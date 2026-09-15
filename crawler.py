#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Newspaper downloader entry script.

Usage (the authoritative reference is ``--help``, not this docstring):
    python crawler.py              interactive menu when run on a TTY with no args
    python crawler.py --help       all subcommands, options, examples and exit codes
    python crawler.py sites        list available sites
    python crawler.py plan ...     dry-run: days that would be fetched or skipped
    python crawler.py crawl ...    fetch

Implementation lives in ``newspaper_crawler.cli``.
"""

import sys

from newspaper_crawler.cli import main

if __name__ == "__main__":
    sys.exit(main())
