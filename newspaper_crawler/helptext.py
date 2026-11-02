"""Help texts: the canonical user documentation of every subcommand.

``README`` points at ``--help`` as the authoritative reference, so these strings are
product surface, not comments: keep them in sync with the flags and JSON fields in
``cli`` and with ``IO_AND_EXIT``.
"""

from __future__ import annotations

IO_AND_EXIT = """\
输出与退出码:
  结果写 stdout，进度与日志写 stderr；--json 时 stdout 为单个 JSON 对象。
  0    成功（含「当日无报纸」这类正常空结果）
  1    运行期错误（抓取失败、站点无法识别等）
  2    用法或参数错误
  130  被 Ctrl+C 中断"""

MAIN_EPILOG = f"""\
无参数且处于终端时进入交互式菜单。偏好与运行账本存于当前目录的
.newspaper-crawler.json，未显式给出的参数会沿用其中的上次取值。

示例:
  crawler sites --json
  crawler plan  --sites rmrb --start 2026-09-01 --end 2026-09-03 --json
  crawler crawl --sites rmrb,gmrb --start 2026-09-01 --end 2026-09-03
  crawler crawl --sites 人民 --fast          # 站点可用 ID / 名称 / 别名
  crawler runs --json                        # 运行历史与未完成日期
  crawler crawl --resume                     # 续跑上次未完成的日期

{IO_AND_EXIT}"""

SITES_EPILOG = """\
列出站点 ID、名称与别名，供 --sites 参数使用。

示例:
  crawler sites
  crawler sites --json"""

PLAN_EPILOG = """\
不联网、不写盘：按输出目录中已存在的文件或上次运行的账本，判断每个「站点 × 日期」
将抓取还是跳过。

示例:
  crawler plan --sites rmrb --start 2026-09-01 --end 2026-09-03
  crawler plan --sites all --json
  crawler plan --resume --json                  # 只预演上次未完成的日期

--resume:
  只处理上次运行中仍为 pending（中断）或 failed（失败）的日期；无账本时报错退出（退出码 1）。
  续传按账本执行，--sites/--start/--end/-o/-f 一律忽略（用账本记录的值）。

--json 输出字段:
  sites / unknown_sites / start_date / end_date / output_dir / format / resumed
  days     [{site, date, path, exists, status, action}]，action 为 fetch 或 skip；
           status 为账本状态（pending/failed/done/skipped/empty），非续传时为 null
  summary  {"fetch": N, "skip": N}"""

CRAWL_EPILOG = """\
示例:
  crawler crawl                                    # 全部站点，最近 7 天
  crawler crawl --sites rmrb --start 20260901 --end 20260903
  crawler crawl --sites all -o ~/paper -f txt --workers 8 --fast
  crawler crawl --sites all --site-workers 1       # 站点改为串行（调试用）
  crawler crawl --resume                           # 只重跑上次未完成的日期
  crawler crawl --sites nope --json                # 站点无法识别 → 退出码 1

站点调度:
  多个站点默认并行（不同站点是不同主机，互不影响对方请求频率）；
  --site-workers 控制并行站点数，--workers 控制单站点的请求并发数
  （版面页与文章共用；调低会显著变慢，--workers 1 即串行）。

状态持久化:
  偏好与运行账本存于当前目录的 .newspaper-crawler.json（可用 CRAWLER_STATE 覆盖路径）。
  未显式给出的参数沿用该文件中的上次取值；--resume 则按账本只重跑 pending/failed
  的日期，用 crawler runs 查看历史。--resume 按账本执行，--sites/--start/--end/
  -o/-f 一律忽略；账本里已不存在的站点会报错并跳过，不再写回新账本。

--json 输出字段:
  ok              是否没有日级失败与未识别站点（单篇正文抓取失败只计入
                  stats.total_errors，不影响 ok；以 stats 为准）
  sites           实际抓取的站点 ID
  unknown_sites   无法识别的站点输入
  output_dir      输出目录（绝对路径）
  start_date / end_date / format / elapsed_secs
  resumed         是否续传模式
  stats           days_attempted / days_success / days_skipped / days_empty /
                  total_editions / total_articles / total_errors
  files           本次写入的文件路径
  skipped         因已存在而跳过的文件路径
  errors          [{"site": ..., "date": ..., "message": ...}]
  warnings        同上格式；含无法识别的站点、索引页结构疑似变化等（不影响 ok）"""

RUNS_EPILOG = """\
列出本目录账本中的运行历史，以及上次运行仍未完成的日期。

示例:
  crawler runs
  crawler runs --json

--json 输出字段:
  last_run    {run_id, started_at, output_dir, format, stats, summary}
  open_days   [{site, date, status, path, error}]，status 为 pending 或 failed
  open_count  未完成条数（= len(open_days)）
  history     [{run_id, started_at, sites, summary}]，最近 20 条
  state_file  账本文件路径"""

