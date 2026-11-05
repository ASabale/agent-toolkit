# Skills.sh remote install proof

Date: 2026-11-05. Published source: `https://github.com/ASabale/agent-toolkit.git`, default branch `ASabale/agent-toolkit@b580644` (squash of pull request #198). Sandbox `HOME=/tmp/skills-remote.UcAvje` (not the real home). The primary checkout was not the install target.

## Results

| Check | Result | Exit | Evidence |
| --- | --- | --- | --- |
| `npx --yes skills add ASabale/agent-toolkit --yes --all` | pass | 0 | stdout: `Source: https://github.com/ASabale/agent-toolkit.git`, `Installed 1 skill` at `./.agents/skills/agent-toolkit`. Stderr empty. |
| skills.sh page | listed, no rank |  | `https://skills.sh/ASabale/agent-toolkit` fetched the same day showed 1 skill and 2 total installs. No rank was on the page. |
| `git clone --depth 1` into `$HOME/.agent-toolkit` | pass | 0 | clone of the GitHub default branch |
| `$HOME/.agent-toolkit/install.sh` | pass | 0 | stdout `installed: true` and `check.ok: true` (41 checked). Stderr was the `hooksPath_unchanged` JSON note. |
| `tk` on `PATH` | pass | 0 | `command -v tk` → `$HOME/.local/bin/tk` |
| `tk find "lint wiki"` | pass | 0 | `wiki.lint` plus `run: tk run wiki.lint --path wiki` |
| `tk run wiki.lint --path wiki` from the clone | pass | 0 | `{"ok":true,"path":"wiki","pages":16,"orphans":[],"broken_links":[],"undated_pages":[],"bad_citations":[]}` |
| same command with cwd = sandbox `HOME` | fail | 1 | stderr `{"error":"not_a_directory","why":"wiki is not a directory","fix":"tk run wiki.lint --path wiki"}`. That `fix` is the command that just failed. |

## Notes

- The CLI also printed Socket "1 alert" and Snyk "Med Risk" and did not name the finding. This run did not investigate it.
- `diff` of `$HOME/.agents/skills/agent-toolkit/SKILL.md` against the clone's `skills/agent-toolkit/SKILL.md` was empty. A second copy at `$HOME/agent/skills/agent-toolkit/SKILL.md` wrapped the YAML description and dropped one blank line.
- Issue #200 is the looping `fix`. Issue #199 (chain step identity) was filed the same day and not claimed.

## Related

- [2026-11-05 skills-add proof](2026-11-05-skills-add-proof.md) — same day, local path `npx skills add /Users/akshay/Development/agent-toolkit`, not the GitHub slug.
- [2026-11-04 master-mission baseline](2026-11-04-master-mission-baseline.md)
- [0005 — Chief-of-Staff decision log](../decisions/0005-chief-of-staff-decision-log.md)
