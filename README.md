# Agent Toolkit (`agent-toolkit`)

A portable, self-evolving CLI toolkit distributed as an agent skill — built to replace bloated, multi-turn MCP servers with deterministic, composable CLI tools that even small models execute reliably.

## Why This Exists

Model Context Protocol (MCP) servers fight how language models actually work:
1. **Context Bloat**: Every connected MCP server dumps dozens of tool schemas into the system prompt on every turn, burning tokens and diluting attention before the agent does any work.
2. **Multi-Turn Ping-Pong**: Completing a 4-step workflow through MCP requires 4 sequential model turns (`call → wait → parse → call`), multiplying latency, cost, and failure surface.
3. **Training Mismatch**: LLMs are deeply pretrained on Linux shells, POSIX flags, pipes, and code — not bespoke JSON-RPC schemas.

**Agent Toolkit** flips the model around three core principles:
- **Minimum Cognitive Load**: One flat grammar (`tk run <tool> --flag <value>`), zero flag-ordering traps, and self-healing errors that print the exact `fix` command. Even small or local models succeed on the first try.
- **Minimum Token Spend**:
  - *Zero idle bloat*: Only a 35-line skill (`skills/toolkit/SKILL.md`) sits in context.
  - *Single-hop discovery*: `tk find "<intent>"` prints the matching tool and its copy-pasteable `tk run` command immediately—no extra inspection turns.
  - *Distilled outputs*: Tools strip API/log noise and emit only compact, decision-ready JSON.
- **Usage-Driven Evolution (Zero Bloat)**: Agents save repeatable multi-step commands (`tk save`), chain tools (`tk chain`), and continuously prune unused or overlapping tools (`tk evolve`) so the toolkit stays small and sharp.

## Repository Layout

```text
agent-toolkit/
├── VISION.md                 # Absolute vision, core thesis, and evolution roadmap
├── AGENTS.md                 # Instructions for agents building and maintaining this repo
├── ARCHITECTURE.md           # Deep-module seams, single-file tool contract, and evolution loop
├── skills/
│   └── toolkit/
│       └── SKILL.md          # Portable skill definition (drop into Claude, Cursor, OMP, Codex)
├── tools/                    # Single-file executable tools (metadata embedded in header)
│   └── .template             # Canonical single-file tool template
├── chains/                   # Saved multi-tool pipelines and composite workflows
├── state/                    # Local usage telemetry, gap journal, and unverified drafts (gitignored)
└── tests/                    # Contract and determinism verification suite
```

## Context Pointers

- Setting direction, evaluating scope, or checking product principles → read [`VISION.md`](VISION.md).
- Designing modules, CLI grammar, tool headers, or composition seams → read [`ARCHITECTURE.md`](ARCHITECTURE.md).
- Working on this repository as a coding agent → read [`AGENTS.md`](AGENTS.md).
- Using or evolving the toolkit from any agentic harness → read [`skills/toolkit/SKILL.md`](skills/toolkit/SKILL.md).
