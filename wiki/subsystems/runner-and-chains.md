# Runner and chains

On 2026-11-03, `ASabale/agent-toolkit@9d469d7` added `lib/runner.py` (472 lines in that commit) and the `tk` entrypoint (421 lines). `CODING_STANDARDS.md` at the same commit named the runner the validation, execution, and chaining seam. Public functions were `parse_cli_flags`, `validate_and_build_env`, `run_tool`, and `run_chain`.

## Flag grammar

On 2026-11-03, `parse_cli_flags` at `ASabale/agent-toolkit@9d469d7` accepted `--dry-run` anywhere in argv, `--flag value`, `--flag=value`, and a bare `--flag` (stored as `"true"`). Tokens that did not start with `--` became positional. This matched the order-independent flag rule written the same day in `AGENTS.md` at `ASabale/agent-toolkit@d4c16aa`. See [0002](../decisions/0002-minimum-cognitive-load-and-tokens.md). *(Superseded on 2026-11-04 by `ASabale/agent-toolkit@46a6538`, which added an optional `item` parameter to `parse_cli_flags(argv, item=None)`: when `item` was supplied, boolean flags only consumed a following boolean literal token rather than swallowing positional arguments, and non-boolean flags accepted values starting with `-` or `--` other than `--dry-run`.)*

On 2026-11-03, `validate_and_build_env` rejected a non-empty positional list with `positional_arguments_forbidden` and `fix` set to the item example. Unknown flags produced `unknown_flag`. Missing required flags produced `missing_required` and a `fix` command that kept already accepted flags and appended `--missing <value>` placeholders. Types were checked as int (no `.`, `e`, or `E`), finite float, bool (`true`/`1`/`yes`/`false`/`0`/`no`), or string. Success returned env `TK_DRY_RUN` of `1` or `0` and `TK_ARG_<NAME>` values, including defaults for omitted optional flags.

## Execution

On 2026-11-03, `run_tool` validated flags, executed `item["path"]`, and required stdout to be compact JSON. Failures became a single-line JSON object on stderr with `error`, `why`, and `fix`. An unexpected exception became `internal_error` with `fix` `tk check`, matching the trust invariant in [0003](../decisions/0003-autonomous-chief-of-staff-governance.md).

On 2026-11-03, `_record_run` skipped logging when `dry_run` was true. A real exit 0 logged `run_ok`. A real non-zero exit logged `run_error` with `why` taken from stderr JSON when that JSON had a `why` string. See [Evolver and quarantine](evolver-and-quarantine.md).

## Chains

On 2026-11-03, `ARCHITECTURE.md` at `ASabale/agent-toolkit@4b0e69c` specified saved chains as `chains/<name>.json` and said a saved chain appears in `tk find` like an atomic tool. `ASabale/agent-toolkit@d4c16aa` kept that composition section while shortening the skill's chaining instructions.

On 2026-11-03, `run_chain` at `ASabale/agent-toolkit@9d469d7` validated chain-level flags, then for each step resolved `$input.<arg>`, `$prev.<path>`, and `$step[i].<path>` into the next tool's flags. Each step's JSON stdout became the next step's previous value. The first error stopped the pipeline (`unknown_tool`, `unresolved_reference`, `invalid_chain`, or the failing tool's own error). `tk run <chain-name>` and `tk chain run <name>` both reached this function. `tk` passed `chains_only=True` for the `chain run` path.

On 2026-11-03, `chains/git.repo-health.json` at `ASabale/agent-toolkit@9d469d7` named `git.repo-health`, safety `read-only`, one required `--repo` string, and two steps: `git.branch-digest` with `repo: "$input.repo"`, then `json.pick` with `keys: "branch,ahead,behind,dirty,detached,upstream"`. Its example was `tk run git.repo-health --repo .` and its `verified` field was `none`.

On 2026-11-04, `ASabale/agent-toolkit@c37e045` updated `parse_cli_flags` in `lib/runner.py` so `--dry-run=0|false|no|off` evaluated to `dry_run=False`, added `TK_TIMEOUT` (default 60s) subprocess timeout protection in `run_tool` returning `error="tool_timeout"`, added `--arg`, `--example`, and `--force` flags to `tk chain save`, and added `chains/gh.triage-pr.json` (`gh.pr-failure-digest` piped into `json.pick` with `keys: "repo,pr,fail,pending,checks"`).

Catalog lookup for those step names went through `discover_catalog`. See [Catalog and check](catalog-and-check.md).

## Related

- [0002 — Minimum cognitive load and tokens](../decisions/0002-minimum-cognitive-load-and-tokens.md)
- [0003 — Autonomous Chief-of-Staff governance](../decisions/0003-autonomous-chief-of-staff-governance.md)
- [Catalog and check](catalog-and-check.md)
- [Evolver and quarantine](evolver-and-quarantine.md)
