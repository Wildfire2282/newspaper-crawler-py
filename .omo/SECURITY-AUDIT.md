# Sensitive-data audit (2026-11-25)

## Scope

- Tracked worktree at HEAD `2a734af`
- The new `.omo/` audit archive (plan, ledger, revisions, per-goal evidence, final gate)
- Full git history (`git log -p --all`)
- The GitHub remote state before the archive push

## Method

Scanned for high-confidence credentials and personal/environment data:

- AWS access keys (`AKIA...` / `ASIA...`)
- GitHub tokens (`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`, `github_pat_`)
- OpenAI-style keys (`sk-...`)
- Slack tokens (`xox...`)
- Google API keys (`AIza...`)
- PEM private keys
- JWTs
- `Authorization: Bearer` headers
- URLs with embedded userinfo
- Password/secret/API-key assignments
- `Cookie:` headers
- Windows/user-home and workspace absolute paths
- Email addresses

## Result

- **No high-confidence secret, token, private key, password assignment, cookie, or credential-bearing URL was found** in current tracked files, the `.omo` archive, or history.
- `.omo` after redaction: **0** local-path hits and **0** email hits.
- Current tracked files contain only the project's public GitHub noreply author address in `pyproject.toml`.
- Historical commits (already public before this audit) contain:
  - developer-local workspace path fragments in old commit diffs;
  - a handful of public newspaper contact addresses in old commit content.
  These are **not credentials**. They were not rewritten because rewriting published history would require a force-push and explicit authorization.
- The internal ulw-loop session UUID remains in `.omo/` because it names the archive directory. It is not a credential.

## Redactions applied before publishing `.omo`

- Local user, workspace and temporary paths replaced with `<home>`, `<repo>`, `<temp>`, `<run-tmp>` and `<qa-tmp>`.
- Newspaper article bodies replaced with `<redacted: newspaper article body>`; JSON keeps paragraph counts and SHA-256 hashes.
- The generated 344 KB Markdown issue was replaced with a summary in `G002/live-crawl.md`.
- Lock/temp files are excluded by `.omo/.gitignore`; `.venv`, caches, build output and downloaded files are not archived.

## Residual notes

- Public GitHub noreply addresses remain in project metadata and commit trailers.
- No force-push or history rewrite was performed.
