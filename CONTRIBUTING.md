# Contributing

External humans and agents contribute with their own GitHub account and a fork of [ASabale/agent-toolkit](https://github.com/ASabale/agent-toolkit). Write access to this repository is not required. Do not open the pull request as `ASabale`, and do not apply repository labels you cannot set.

[`COORDINATION.md`](COORDINATION.md) is the protocol for agents that already operate as the repository identity and can push branches here. Independent contributors follow this file. The Steward still merges. A suggestion is not a commitment to implement it.

Evaluate changes by usefulness, evidence, and [`VISION.md`](VISION.md): easy to use, easy to extend, easy to maintain. Do not invent usage numbers, adoption counts, or feedback that did not happen.

## Channels

| You have | Where |
| --- | --- |
| A real `tk` run and what happened | [Feedback](https://github.com/ASabale/agent-toolkit/issues/new?template=feedback.yml) |
| A broken command you can re-run | [Bug](https://github.com/ASabale/agent-toolkit/issues/new?template=bug.yml) |
| A capability or workflow backed by a real task | [Proposal](https://github.com/ASabale/agent-toolkit/issues/new?template=proposal.yml) |
| An architectural idea, not yet a change | [Ideas](https://github.com/ASabale/agent-toolkit/discussions/new?category=ideas) |
| A question or design conversation | [General](https://github.com/ASabale/agent-toolkit/discussions/new?category=general) |
| Something you already built and want to show | [Show and tell](https://github.com/ASabale/agent-toolkit/discussions/new?category=show-and-tell) |
| A code change | A pull request from your fork |

Agents that maintain this repo triage reports with [`FEEDBACK.md`](FEEDBACK.md). The work-item template is how a maintainer turns a kept report into a build ticket. External contributors do not need it to file feedback, bugs, or proposals.

## Pull requests

1. Fork the repository and clone your fork.
2. Branch from current `main`. Any branch name is fine. You do not need `<agent>/<issue>-<slug>`.
3. Change the smallest surface that does the job. Match the surrounding files. One tool is one executable under `tools/` with its `# @tk-*` header in that file.
4. Behavior changes need a test that fails without the change and passes with it. Run:

```bash
./tk check
python3 -m unittest discover -s tests
TK_NO_TELEMETRY=1 python3 -m unittest discover -s tests
```

5. Open the pull request against `main` from your fork. In the body, state what changed, why it fits `VISION.md`, the commands you ran, and `Closes #N` when an issue exists. A fork pull request can be reviewed without that link when no issue exists yet.

Maintainer agents reproduce the change themselves. CI on `pull_request` is the check they trust. Do not ask a reviewer to run untrusted code from a comment as a substitute for a test in the branch.

## Secrets and workflows

`.github/workflows/ci.yml` runs on `pull_request` and `push`. It does not receive repository secrets. Fork pull requests get the default read-only `GITHUB_TOKEN` for that event.

Do not switch those workflows to `pull_request_target`. Do not add `secrets.*` to a workflow that runs on untrusted pull requests. Do not echo tokens, `.env` files, or credentials in logs or tests. A change to CI, `install.sh`, the runner, or `COORDINATION.md` gets a full Steward review.

Branch protection stays as it is. The required check is the job named `test`. Do not rename or remove it. Only the Steward or the owner changes repository settings. This file does not grant merge rights.

## Discussions

GitHub Discussions are already enabled on `ASabale/agent-toolkit`. Categories in use: General, Ideas, Q&A, Show and tell, Announcements, Polls. No settings change is required.

If a future clone has Discussions turned off, the owner enables them manually: repository **Settings → General → Features → Discussions**. That checkbox is not in this repository's files, and agents must not try to flip it by editing code.
