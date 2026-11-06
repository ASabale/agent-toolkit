# Baseline

Recorded 2026-11-05 on `plan/t0.1-baseline` at `3f2a3cd3f7148248830ee66fc7a53ff4c950e6ce` (`main`).
Local interpreter: Python 3.14.4. `TK_NO_TELEMETRY=1`. Unit tests used a fresh `TK_STATE_DIR`.
`py39` and `shellcheck` from `.github/workflows/ci.yml` were not run on this machine.

## Suite

| Command | Result | Runtime (real) |
|---|---|---|
| `./tk check --json` | exit 0, `ok: true`, `checked: 41`, `errors: []` | 1.54s |
| `python3 -m unittest discover -s tests` | `Ran 455 tests` / `OK` | 211.44s (test clock 211.314s) |
| `./tk run wiki.lint --path wiki` | `{"ok": true}` | 1.65s |

`tk check` covers 39 tool files plus 2 chain files.

## Size

| Item | Value |
|---|---|
| `skills/agent-toolkit/SKILL.md` lines | 51 |
| `skills/agent-toolkit/SKILL.md` words (`wc -w`) | 397 |
| `skills/agent-toolkit/SKILL.md` bytes | 2625 |
| Token estimate (`words × 1.4`) | 556 |
| Tool files (`tools/**`, excluding `.template` and `__pycache__`) | 39 |
| Chain files (`chains/*.json`) | 2 (`gh.triage-pr`, `git.repo-audit`) |

`CODING_STANDARDS.md` §3 already caps that skill at 51 lines and 2700 bytes. This measurement sits on the line cap and 75 bytes under the byte cap.

## `tk find` stdout size (characters)

stderr was empty and exit was 0 for each query. `TK_NO_TELEMETRY=1`.

| Query | stdout characters |
|---|---|
| *(empty)* | 6156 |
| `failing checks` | 320 |
| `git blame` | 729 |
| `search code` | 777 |

Empty-query output is the full catalog: two lines per tool or chain (`tests/test_token_budget.py`).
