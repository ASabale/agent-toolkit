# Probation audit

On 2026-11-05, at `ASabale/agent-toolkit@cbb13c3`, these catalog names were still present and no file under `chains/` referenced them:

- Decision 0008, added in `ASabale/agent-toolkit@5a57fcd` with no cited origin: `code.todos`, `fs.read-slice`, `json.diff`, `sec.secret-scan`, `docker.ps-digest`.
- The `5aece9a` review, kept on probation: `gh.pr-diff-digest`, `http.health-probe`, `data.csv-digest`.

`tk prune --unused` still waits for 50 `run_ok` or `run_error` events. This audit does not archive them and does not lower that floor.

Phase 4 stays the two chains already on that commit, `gh.triage-pr` and `git.repo-audit`. A new chain that imitates a Bitbucket, Jenkins, or Kubernetes workflow would be a speculative catalog entry. The mission's fixture demo waits until a repeated task uses tools that already exist.

## Related

- [0008 — Tool probation](../decisions/0008-tool-probation.md)
- [5aece9a — Tool review](../decisions/5aece9a-tool-review.md)
- [2026-11-04 master-mission baseline](2026-11-04-master-mission-baseline.md)
