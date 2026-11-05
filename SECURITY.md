# Security

`tk` runs tools on the machine where you invoke it. There is no account, registry, or remote tool download.

- Do not put secrets, tokens, or credentials in a tool file, a chain file, `stdout`, `stderr`, or `state/events.jsonl`.
- Leave credentials in the caller environment. A GitHub tool uses the existing `gh` login. It does not store a token in the catalog.
- A mutating or destructive `tk run` returns `plan` and does not change anything until the same command includes `--yes`.
- Check a tool with `tk check <name>` before you rely on it. Do not run a script you have not read.
- The lint is not a sandbox; tools run as the user.
