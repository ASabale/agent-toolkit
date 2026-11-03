# Agent Toolkit (`agent-toolkit`)

A portable, self-evolving CLI toolkit distributed as an agent skill — built to replace bloated, multi-turn MCP servers with deterministic, composable CLI tools that even small models execute reliably.

## Why This Exists

Model Context Protocol (MCP) servers fight how language models actually work:
1. **Context Bloat**: Every connected MCP server dumps dozens of tool schemas into the system prompt on every turn, burning tokens and diluting attention before the agent does any work.
2. **Multi-Turn Ping-Pong**: Completing a 4-step workflow through MCP requires 4 sequential model turns (`call → wait → parse → call`), multiplying latency, cost, and failure surface.
3. **Training Mismatch**: LLMs are deeply pretrained on Linux shells, POSIX flags, pipes, and code — not bespoke JSON-RPC schemas.

**Agent Toolkit** flips the model:
- **Skill-First Discovery (Zero Idle Bloat)**: A single lightweight skill (`skills/toolkit/SKILL.md`) sits in context. Full tool schemas load only on demand via CLI discovery.
- **Deterministic for Small Models**: Uniform grammar, copy-pasteable invocation examples, strict argument validation, and structured JSON output allow fast, cheap, or local models to execute actions deterministically on the first try.
- **Composable by Default**: Tools speak standard `stdin`/`stdout` JSON and chain via UNIX pipes (`|`) or saved multi-step chains — collapsing 5 turns of MCP calls into 1 deterministic command.
- **Self-Evolving**: Agents are authors, not just callers. Agents save frequently used commands, author new tools in a single file, chain existing tools together, and automatically promote recurring workflows into verified tools.

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
