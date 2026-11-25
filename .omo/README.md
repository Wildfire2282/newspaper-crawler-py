# ulw-loop audit archive

This directory archives the completed 10-goal / 31-criterion ulw-loop run:
ulw-loop/<session>/ holds the brief, goals, ledger and revision snapshots;
evidence/ulw/<session>/ holds the per-goal acceptance artifacts and the final
quality gate (manual QA, reviewer report, iteration log).

## Redactions before publication

- Local user, workspace and temporary paths were replaced with <home>, <repo>,
  <temp>, <run-tmp> and <qa-tmp>.
- Newspaper article bodies were replaced with <redacted: newspaper article body>;
  JSON keeps paragraph counts and SHA-256 hashes. The 344 KB generated Markdown issue
  was replaced with a summary in G002/live-crawl.md.
- The internal session UUID is retained because it names the archive directory; it is
  not a credential. Public GitHub noreply addresses remain in project metadata.

## Not archived

Lock files, caches, the virtualenv and downloaded output files are not part of this
archive. The code changes are in the git history, not in .omo/.
