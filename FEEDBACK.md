# Feedback triage

Maintainer agents use this procedure on reports other people filed. Do not file placeholder feedback, and do not invent volume or adoption numbers. A small agent can file a report. A maintainer agent investigates. Another agent implements only when the report is worth keeping.

External reporters follow [`CONTRIBUTING.md`](CONTRIBUTING.md). They do not need this procedure, write access, or the `ASabale` account.

## Discover

```bash
gh issue list --repo ASabale/agent-toolkit --state open --limit 50 \
  --search "label:feedback,bug,enhancement"
```

Read the body. Also search closed issues and [Discussions](https://github.com/ASabale/agent-toolkit/discussions) before opening a second ticket for the same command or the same error string.

## Classify

Group reports that share a command, an error string, or a job. Note the group in a comment on each issue. Leave the original body intact.

| Kind | Label | Next step |
| --- | --- | --- |
| Usage report | `feedback` | Judge against VISION. Do not treat it as a build ticket. |
| Broken, re-runnable command | `bug` | Reproduce, then a work item if the bug is real. |
| Capability backed by a real task | `enhancement` | Judge against VISION, then a work item if it earns a tool or a change. |
| Design conversation | Discussion | Leave it there until someone has evidence from a real run. |

## Reproduce

Run the reported command yourself when the report includes one. Record the exit code and the distilled output in a comment. If you cannot reproduce, say which fact is missing and stop. Do not patch from a guess.

## Keep or decline

Keep a report only when it serves [`VISION.md`](VISION.md): less cognitive load, fewer tokens, or a smaller toolkit. Decline reports that add a second command grammar, a speculative tool, token bloat, or a harness-only duplicate of Read, Grep, or a single shell command.

Decline in a comment that names the pillar it breaks, then close the issue. Closing keeps the thread. Do not delete the issue.

## Turn a keeper into work

File a work item with the work-item template, or comment a concrete acceptance list on an existing issue. Link every source report. The work item's Files section is the allowed scope for the pull request. Do not implement from the feedback thread alone.

When a pull request exists, comment the link on each source report. When the change is merged, comment what shipped and close the source report if the reported job is done. The comments are the history.

## Comment shape

```text
Triage: <feedback|bug|proposal|duplicate of #N>
Group: <shared command or error, or "none">
Repro: <command and result, or "not run: missing X">
VISION: <keep: pillar | decline: pillar>
Work: <link to issue or PR, or "none">
```
