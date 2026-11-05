# 0012 — Capability pack contract

On 2026-11-05, at `ASabale/agent-toolkit@d273be3`, a pack is a git directory. There is no registry, no account, and no pack installer. This page states the minimum an independent installation may copy. It adds no `tk` subcommand and no catalog entry.

## What a pack contains

- `tools/`: single-file executables whose headers use the existing `# @tk-*` contract.
- `chains/*.json`, optional: chain files that use the existing chain schema (`name`, `steps`, `args`).

A receiving install may copy those files into its own `tools/` and `chains/`. It must not copy anything else from the pack as a capability. After the copy, `tk check` on the receiving install is the acceptance check.

## What a pack must not contain

Secrets, hostnames, and absolute home paths are invalid pack contents. A file that contains any of those is not a capability to copy. Credentials stay in the receiving machine's environment, outside the pack.

## Related

- [0001 — Clean-slate single-file contract](0001-clean-slate-single-file-contract.md)
