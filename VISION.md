# Absolute Vision: Agent Toolkit

## 1. The Core Problem

Modern agentic harnesses rely heavily on MCP (Model Context Protocol) servers to interact with external systems. In practice, MCP creates three compounding bottlenecks:

1. **System Context Bloat**: Every active MCP registers all of its tool definitions in the always-loaded system prompt. Ten MCPs easily consume 15k–40k tokens before the first user message, degrading reasoning and triggering early context compaction.
2. **Multi-Turn Tool Ping-Pong**: MCP tools are atomic RPC calls. To fetch an issue, inspect its linked PR, check failing CI logs, and post a summary, an agent must execute four separate model turns—paying full context prefill and latency on every hop.
3. **Hostile Ergonomics for Smaller Models**: Frontier models can sometimes recover from ambiguous MCP schemas; smaller, faster, or local models hallucinate nested JSON parameters, misread undocumented state preconditions, and loop on opaque errors.

Meanwhile, language models already possess a superpower from pretraining: **they are native citizens of the Linux CLI and code execution environment.** They understand flags, exit codes, pipes, `jq`, and scripts better than any custom protocol.

---

## 2. Purpose & Core Principles

**Purpose**: Enable any agent to **get the job done** with **minimum cognitive load** and **minimum tokens**, while making the toolkit effortless to use and evolve.

Replace static, context-heavy MCP servers with a **portable, self-evolving CLI toolkit packaged as an Agent Skill**. Once a user drops this toolkit into any agentic harness (OMP, Claude Code, Cursor, Codex, Devin), they can **turn off MCP servers entirely**.

Every decision in `agent-toolkit` is governed by three non-negotiable principles:

1. **Minimum Model Cognitive Load**: The toolkit must require near-zero reasoning to understand. One flat command shape, zero ordering traps, self-explanatory flags, and errors that print the exact corrected command. Even a small or local model succeeds on the first try.
2. **Minimum Token Footprint**: We optimize relentlessly for the lowest total tokens across the entire task lifecycle:
   - **Zero idle tokens**: Only a compact skill pointer sits in context; tool definitions stay on disk until needed.
   - **Minimum discovery tokens**: `tk find` returns the matching tool *and* its exact copy-pasteable `tk run` signature in two lines—eliminating extra inspection turns.
   - **Minimum output tokens**: Tools are **distillers**, not raw API pipes. A tool filters out noise and emits only the compact, high-signal data required to complete the job.
3. **Continuous Usage-Driven Evolution**: Agents are both consumers and authors. When an agent solves a task or hits friction, it saves or refines the tool on the spot, chains multi-step workflows into one call, and prunes stale tools so bloat never returns.

---

## 3. The Three Pillars

### Pillar I: Easy to Use (Zero Cognitive Load, Minimum Tokens)

If a 7B–30B model cannot use a tool on the first try without wasting turns or tokens, the tool's interface is broken.

- **One Uniform Grammar**: Every invocation follows the exact same shape:
  ```bash
  tk run <tool> [--flag <value> ...]
  ```
  No positional arguments, no order-dependent global flags (never repeat the `--instance`-before-plane trap of earlier harnesses), and no implicit environment magic.
- **Two-Step Execution (`Find → Run`)**:
  1. `tk find "<intent>"` returns ranked matches **with their required flags and copy-pasteable example inline** (no mandatory `tk info` round-trip before running).
  2. `tk run <tool> ...` executes deterministically and emits distilled, low-token JSON. (`tk info <tool>` exists only when deep contract inspection is needed.)
- **Distilled Output by Default**: A tool that dumps 5,000 tokens of raw API JSON into context has failed. Tools strip noise, paginate, and return only the fields the agent needs to act.
- **Self-Healing Errors**: When a flag is missing or an upstream call fails, `stderr` states *what failed*, *why*, and the *exact copy-pasteable `fix` command*—so a model repairs the call in one step without burning thinking tokens.

### Pillar II: Easy to Extend (Single-File Tools & Seamless Chaining)

Adding or composing a tool must take seconds, not boilerplate across multiple directories.

- **Single-File Tool Contract**: A tool is a single executable file in `tools/` (Bash, Python, TypeScript/Bun, or any shebang script) with structured `# @tk-*` metadata in its header comment. **Zero sidecar `.yaml` files**—metadata and implementation live in one file and cannot drift apart.
- **Save & Promote in One Command**:
  - `tk save <name> --from-cmd "<command>"` or `tk save <name> --file <script>` turns a working one-liner or script into a first-class indexed tool with parameter placeholders, description, and example.
- **Native Chaining**:
  - **UNIX Pipes**: Every tool emits clean JSON on `stdout` (or accepts `--raw`), making `tk run gh-pr-list | jq ... | tk run slack-notify` trivial.
  - **Saved Chains**: `tk chain <name> <step1> <step2> ...` records a multi-tool pipeline as a single deterministic command so agents execute complex multi-step workflows in a single tool call.

### Pillar III: Easy to Maintain (Self-Validating, Self-Evolving & Self-Pruning)

A toolkit that rots or accumulates unverified junk becomes worse than no toolkit.

- **Single Source of Truth**: The catalog is built directly from tool headers and chain definitions. There is no separate registry file to keep in sync.
- **Anti-Bloat & Pruning Discipline**: Tools change over time; if the toolkit only adds and never subtracts, it recreates MCP bloat inside `tools/`.
  - **Earn Your Keep**: Every tool is tracked by actual invocation frequency and failure rate in `state/events.jsonl`.
  - **Consolidate or Prune**: Redundant tools are merged into parameterized tools or chains; stale, superseded, or zero-use tools are pruned via `tk prune` / `tk evolve`.
  - **No Speculative Tools**: Tools are born strictly from real usage friction, never invented "just in case."
- **Automatic Evolution with Safety Gates**:
  - **Friction & Usage Capture**: Every missed `tk find` query, failed `tk run`, and repeated command pattern is appended to `state/events.jsonl`.
  - **Tiered Promotion**:
    - `read-only` tools auto-promote to the catalog once `tk check <tool>` passes syntax, header schema, and a live or dry-run smoke check.
    - `mutating` and `destructive` tools require `--dry-run` support and explicit verification before promotion.
- **Harness-Agnostic Portability**: Zero lock-in to any single IDE, LLM provider, or company infrastructure. Tool packs are plain folders of single-file tools shared via git across any agent harness that supports shell execution and `SKILL.md`.

---

## 4. Lessons Applied from Earlier Attempts (`cli-harness`)

We start from scratch specifically to leave behind the structural debt of the earlier `cli-harness`:

| Earlier `cli-harness` Friction | New `agent-toolkit` Rule |
|---|---|
| Sidecar `.yaml` + `.sh` files drifted constantly | **One file per tool**: header comments inside the executable script are the manifest |
| `--instance <vm> <plane> <cmd>` ordering broke small models | **Flat, uniform `--flag value` grammar**: order never matters |
| Hardcoded 9 company-specific planes & 3-tier folders | **Flat `tools/<namespace>/<verb-noun>` layout**: domain-agnostic, shareable anywhere |
| Heavy manual scaffolding to add a capability | **`tk save` & single-file drop-in**: agents create or promote tools in one step |
| Unbounded accumulation of one-off scripts | **Continuous pruning (`tk evolve` / `tk prune`)**: unused or duplicate tools are retired |

---

## 5. Law of Evolution: Immutable Vision, Infinite Iteration

There is no static "end goal" or finished feature checklist—only **continuous iterations** governed by three permanent rules:

1. **The Vision Is Immutable**: The toolkit may never compromise on its three pillars (*Easy to Use*, *Easy to Extend*, *Easy to Maintain*) or reintroduce context bloat, multi-file boilerplate, or harness lock-in.
2. **Using Is Evolving**: We do not build tools in isolation and hope someone uses them. Whoever uses `agent-toolkit` in real work evolves it on the spot when they hit friction or spot a repeatable pattern.
3. **Subtract to Grow**: Every iteration must leave the toolkit sharper, not larger. Adding a capability, collapsing three steps into one chain, and deleting two obsolete tools are equally vital evolutionary moves.
