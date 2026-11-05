# Decisions that need a human

Defaults are what the next implementation branch will do if no one answers. A default of "do not build" means the branch must not invent the behavior.

None of these edit `VISION.md`. Answering one does not authorize the others.

## D1. When does `--yes` stop running destructive tools?

Today `SECURITY.md` says a mutating or destructive command does nothing until `--yes`. Tests and `apply` strings depend on that.

The review forbids keeping unbound `--yes` as the authorization for destructive work merely so old commands keep working.

Default until you answer: do not change `--yes`. The next branch may add `plan_id` and `--confirm` as an integrity check and must keep the current `--yes` path green.

Proposed migration, for you to accept or reject:

1. Ship `plan_id` and `--confirm` additively. `--yes` still runs mutating and destructive tools. Destructive `--yes` writes a stderr warning and an audit field `via: yes`.
2. After one release, destructive `--yes` is refused with `error` `confirm_required`, `why` naming the plan id, and `fix` the `--confirm <plan_id>` command. Mutating tools still accept `--yes`.
3. Later, and only with another explicit yes, mutating `--yes` warns and then goes through the same refusal.

In-process `run_tool(..., confirmed=True)` stays the library default so tests that mean "execute this tool" do not all flip to dry-run.

Say which step to stop at. Silence means step 1 is not even started until the design branch has landed; step 1 is the default implementation, steps 2 and 3 are not.

## D2. Is there a user tool directory?

There is no `TK_HOME`. `TK_STATE_DIR` overrides state only. A user namespace needs a directory, and a directory is a new discovery root.

Default: do not create one. `user.*` stays a reserved prefix with no loader.

## D3. Do we move files into layer directories?

`tools/gh/pr-checks` and the name `gh.pr-checks` are the catalog agents already call. Moving them to `tools/core/...` breaks clones, docs, and chains for a naming idea the resolver does not need.

Default: no moves. Resolution class is "on the trusted branch" versus "anywhere else." A project file cannot replace a trusted name. Overrides are explicit.

This is the old T3.1 question. The answer is required before any migration. The layer document, if written later, must match this default unless you override it.

## D4. May an MCP import write tools?

Default: no importer and no generated wrappers. A future design may add one generic adapter under `external.*` that does not create a file per remote tool. Building that adapter still needs a yes. MCP annotations are not a security boundary either way.

## D5. May the CLI grow a self-audit surface?

`tk doctor` will not be rebuilt. A read-only self-audit is specified in `ARCHITECTURE_REVIEW.md` §9. `ARCHITECTURE.md` does not list that command. `SKILL.md` cannot grow.

Default: do not add a subcommand, a flag, or a tool until you pick one of: `tk check --audit`, a `meta.self-audit` tool, or neither.

The report must not apply its own recommendations.

## D6. Tool timeout exit code

`TK_TIMEOUT` already kills the process group and exits 1 with `tool_timeout`. The old plan asked for exit 124.

Default: keep exit 1. Agents and tests already have a path for 1. A second timeout mechanism will not be added.

## D7. Optional OS isolation

Seatbelt and bubblewrap can confine some hosts and are missing on others. Neither is a Python dependency we can vendor under the stdlib rule.

Default: do not require them and do not invoke them. The audit record says `isolation: none`. Turning `TK_ISOLATION=seatbelt|bwrap` on, fail-closed when the binary is missing, needs a yes after the audit record exists.

## Not waiting on a human

These already have a default from `VISION.md`, the tests, or the review, and implementation may follow them:

- T1.2 stays skipped. Do not force `fix` to start with `tk`.
- Do not grow `SKILL.md`.
- Policy files, if added, are JSON. Python 3.9 has no `tomllib`.
- File updates use `fcntl.flock` and `os.replace`, not `O_APPEND` alone.
- Regex redaction stays a backstop. Do not log environment values.
- Scripted benches are labeled scripted. They are not agent usability.
- No new default tools under `tools/` unless a task you approved says so.
- No commit to `main` from this program.
