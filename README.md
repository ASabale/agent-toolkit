# Agent Toolkit (`tk`)

`tk` is a portable, self-evolving CLI toolkit packaged as an agent skill. It exists so any agent can get the job done with **minimum cognitive load** and **minimum tokens**, and so the toolkit stays effortless to use and evolve.

MCP servers fight how models work: they dump every tool schema into the system prompt, then require a new model turn for each atomic call. Models already know the Linux CLI. `tk` replaces those servers with one flat grammar, a compact skill pointer in context, and tools that stay on disk until `tk find` / `tk run` needs them.

Drop this folder into any harness that can run a shell (OMP, Claude Code, Cursor, Codex, Devin). You can turn MCP servers off. Tools emit distilled JSON, not raw API dumps. Agents save, chain, and prune from real use so the catalog does not bloat.

## Contribute and report

Your own GitHub account is enough. You do not need write access and you do not post as `ASabale`. Details: [CONTRIBUTING.md](CONTRIBUTING.md). Maintainer triage: [FEEDBACK.md](FEEDBACK.md).

| You have | Open |
| --- | --- |
| A run and what happened | [Feedback](https://github.com/ASabale/agent-toolkit/issues/new?template=feedback.yml) |
| A broken command | [Bug](https://github.com/ASabale/agent-toolkit/issues/new?template=bug.yml) |
| A capability from a real task | [Proposal](https://github.com/ASabale/agent-toolkit/issues/new?template=proposal.yml) |
| An idea, not yet a change | [Ideas](https://github.com/ASabale/agent-toolkit/discussions/new?category=ideas) |
| A question | [General](https://github.com/ASabale/agent-toolkit/discussions/new?category=general) |
| A patch | A pull request from your fork |

## Quick start

```sh
git clone https://github.com/ASabale/agent-toolkit.git
cd agent-toolkit
./install.sh
export PATH="$HOME/.local/bin:$PATH"
tk find wiki
tk run wiki.lint --path wiki
```

`./install.sh` requires `python3` (a missing `python3` exits non-zero with a stderr diagnostic). `gh` is recommended: a missing `gh` prints a stderr warning and install continues. The script creates `~/.local/bin` and `~/.agents/skills` if needed, symlinks `tk` and `skills/agent-toolkit` (and `~/.claude/skills/agent-toolkit` when `~/.claude` exists), and runs `tk check`. It does not set `core.hooksPath`. Stdout is one JSON object:

```text
{"installed":true,"bin":"$HOME/.local/bin/tk","skill":"$HOME/.agents/skills/agent-toolkit","skill_links":["$HOME/.agents/skills/agent-toolkit"],"skill_links_skipped":[],"check":{"ok":true,"checked":...}}
```

Stderr prints the opt-in command for the tracked pre-commit hooks only when `./install.sh` runs inside a git work tree. To enable them:

```sh
git -C <repo> config core.hooksPath .githooks
```

`tk find wiki` prints two lines per match (the runnable command is on the second line):

```text
wiki.lint [read-only] — Report wiki orphans, broken relative links, and pages missing a date or commit
  run: tk run wiki.lint --path wiki
```

`tk run wiki.lint --path wiki` prints distilled JSON:

```text
{"ok":true,"path":"wiki","pages":...,"orphans":[],"broken_links":[],"undated_pages":[]}
```

Point the harness at `~/.agents/skills/agent-toolkit/SKILL.md` (or `~/.claude/skills/agent-toolkit/SKILL.md`).

Agents: skip to [For agents](#for-agents).

## For humans

| Term | Meaning |
| --- | --- |
| **tool** | One executable under `tools/` whose `# @tk-*` header is the contract. No sidecar YAML. |
| **chain** | A saved pipeline in `chains/<name>.json`. Run it with `tk run <name>` like a tool. |
| **skill pointer** | Compact [`skills/agent-toolkit/SKILL.md`](skills/agent-toolkit/SKILL.md) kept in context; tool definitions stay on disk. |
| **`tk find`** | Ranks tools and chains by intent and prints a copy-pasteable `tk run` example. |
| **`tk check`** | Validates headers, flags, and catalog integrity without running the tool. `tk check <name> --verify` runs it through the runner. |
| **`tk evolve`** | Promotes passing unverified read-only items after a live run; reports unused, failing, overlapping, and chain candidates. |
| **`tk prune`** | Archives named or unused items to `state/archive/`. Refuses if a kept chain still uses one. |
| **quarantine** | A failed `tk save` / `tk chain save` draft is copied to `state/quarantine/` and removed from the catalog. |
| **wiki** | Dated, commit-cited history under `wiki/`, linted by `wiki.lint`. |
| **`tk save`** | Turns a working command or script into a catalog tool after `tk check` passes. |

Read next: [VISION.md](VISION.md) (why this exists), [ARCHITECTURE.md](ARCHITECTURE.md) (how it is built), [CODING_STANDARDS.md](CODING_STANDARDS.md) (contracts), [COORDINATION.md](COORDINATION.md) (how this repo is changed), [wiki/index.md](wiki/index.md) (history).

## For agents

**Purpose**: minimum turns and tokens. Find → run. Evolve on friction. Stay lean.

- Grammar: `tk run <name> [--flag <value> ...] [--dry-run]` — named flags only; order never matters.
- Discover: `tk find "<intent>"` → two lines per match (`<name> [<safety>] — <summary>` then `  run: <example>`).
- Run: compact JSON on `stdout`. On failure, `stderr` is `{"error","why","fix"}` — execute `fix`.
- Inspect: `tk info <name>` only when the example is not enough.
- Compose: `tk run <a> | tk run <b>` or `tk run <chain>`.
- Create: `tk save` / `tk chain save`, then `tk check <name>`. Invalid drafts are quarantined.
- Maintain: `tk evolve` (promote + friction report); `tk prune` (archive).
- Commands: `find`, `info`, `run`, `chain`, `save`, `check`, `evolve`, `prune`.
- Skill: [`skills/agent-toolkit/SKILL.md`](skills/agent-toolkit/SKILL.md) (install links `~/.agents/skills/agent-toolkit`, and `~/.claude/skills/agent-toolkit` when `~/.claude` exists).
- Building this repo: [`AGENTS.md`](AGENTS.md), [`COORDINATION.md`](COORDINATION.md).
- Feedback from real use: [Feedback](https://github.com/ASabale/agent-toolkit/issues/new?template=feedback.yml), [Bug](https://github.com/ASabale/agent-toolkit/issues/new?template=bug.yml), [Proposal](https://github.com/ASabale/agent-toolkit/issues/new?template=proposal.yml), or [Discussions](https://github.com/ASabale/agent-toolkit/discussions). A code change is a pull request from your fork. [CONTRIBUTING.md](CONTRIBUTING.md). Agents keep a report only when it fits [`VISION.md`](VISION.md) ([FEEDBACK.md](FEEDBACK.md)).
- Contracts: [`ARCHITECTURE.md`](ARCHITECTURE.md), [`CODING_STANDARDS.md`](CODING_STANDARDS.md).
- Authority: [`VISION.md`](VISION.md). History: [`wiki/index.md`](wiki/index.md).

## Platforms

Python 3.9 or newer, using the system `python3`. `./install.sh` exits non-zero when `python3` is missing. `gh` is optional. At `ASabale/agent-toolkit@cbb13c3`, `.github/workflows/ci.yml` runs the suite on `ubuntu-latest` and `macos-latest`, and runs the unit tests again on Python 3.9.

## Troubleshooting

- `tk` is not on `PATH` after install: `export PATH="$HOME/.local/bin:$PATH"`.
- A mutating or destructive run returned `plan` and changed nothing: run the same command with `--yes`. See [SECURITY.md](SECURITY.md).
- `stderr` is one JSON object with `error`, `why`, and `fix`: run the `fix` command.

## License

MIT — see [LICENSE](LICENSE).

## skills.sh

```sh
npx skills add ASabale/agent-toolkit
```

[![skills.sh](https://skills.sh/b/ASabale/agent-toolkit)](https://skills.sh/ASabale/agent-toolkit)
