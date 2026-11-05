# Skills.sh bootstrap proof

Date: 2026-11-05. Repo: `/Users/akshay/Development/agent-toolkit`. Checkout `905c499` is not an ancestor of main; on 2026-11-05 `git diff 905c499 ASabale/agent-toolkit@b580644` was empty. Sandbox `HOME=/tmp/skills-proof.UmW0ct` (not the real home). No npm global install. `install.sh` has no `PREFIX`; it writes `${HOME}/.local/bin/tk` and `${HOME}/.agents/skills/agent-toolkit`.

## Results

| Check | Result | Exit | One-line stdout |
| --- | --- | --- | --- |
| skills CLI present | pass | 0 | `Usage: skills <command> [options]` (`npx --yes skills --help`) |
| skill install | pass | 0 | `Installed 1 skill` at `./.agents/skills/agent-toolkit` (cwd = temp HOME; source path validated) |
| tk on PATH in sandbox | pass | 0 | `which tk` → `/tmp/skills-proof.UmW0ct/.local/bin/tk` (symlink to repo `tk`) |
| `tk find "lint wiki"` | pass | 0 | `wiki.lint [read-only] — Report wiki orphans, broken relative links, and pages missing a date or commit` |
| one run (`tk run wiki.lint` from repo, sandbox HOME) | pass | 0 | `{"ok":false,"path":"wiki","pages":17,"orphans":["reports/2026-11-04-master-mission-baseline.md"],"broken_links":[],"undated_pages":[],"bad_citations":[]}` |
| `tk check` | pass | 0 | `{"ok":true,"checked":41,...}` |
| unittest | fail | 1 | (quiet; summary on stderr) `Ran 451 tests in 156.256s` / `FAILED (failures=1)` |

## Failing command

```bash
TK_NO_TELEMETRY=1 python3 -m unittest discover -s tests -q
```

```
FAIL: test_repo_wiki_has_no_integrity_findings (test_token_budget.TokenBudgetTests)
AssertionError: False is not true
  File ".../tests/test_token_budget.py", line 80, in test_repo_wiki_has_no_integrity_findings
    self.assertTrue(payload["ok"])
```

Same orphan `wiki.lint` reported: `reports/2026-11-04-master-mission-baseline.md`. Command exit is 1 (`FAILED (failures=1)`).

## Notes

- `npx skills add /Users/akshay/Development/agent-toolkit --yes --all` with `HOME` and cwd set to the temp dir exited 0. Stderr empty. It installed one skill and skipped agents whose project directories were absent.
- `HOME=<temp> ./install.sh` exited 0. Stderr: `hooksPath_unchanged` (install does not set `core.hooksPath`).
- A `tk run wiki.lint` started with cwd = temp HOME (not the repo) exited 1, empty stdout, stderr: `{"error":"not_a_directory","why":"wiki is not a directory","fix":"tk run wiki.lint --path wiki"}`. The recorded run above is the repo-cwd retry.
- `TK_NO_TELEMETRY=1 tk run env.check` in the same sandbox exited 0: `{"ok":true,"binaries":[{"name":"git","found":true,"path":"/usr/bin/git"},{"name":"python3","found":true,"path":"/usr/bin/python3"}],"variables":[],"missing_bins":[],"missing_vars":[]}`.
- Bootstrap path from `skills/agent-toolkit/SKILL.md` works when `HOME` is sandboxed: `install.sh` then `PATH="$HOME/.local/bin:$PATH"`.
