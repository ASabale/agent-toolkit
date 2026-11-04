#!/bin/sh
# Idempotent install: symlink tk and the toolkit skill into the user paths,
# and configure git to use tracked hooks from .githooks/ when inside a git work tree.
set -eu
REPO_ROOT=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
mkdir -p "${HOME}/.local/bin" "${HOME}/.agents/skills"
ln -sfn "${REPO_ROOT}/tk" "${HOME}/.local/bin/tk"
ln -sfn "${REPO_ROOT}/skills/toolkit" "${HOME}/.agents/skills/toolkit"
hooks_path=""
if git -C "${REPO_ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git -C "${REPO_ROOT}" config core.hooksPath .githooks
    hooks_path=".githooks"
fi
check_out=$("${REPO_ROOT}/tk" check --json)
if [ -n "$hooks_path" ]; then
    printf '%s\n' "{\"installed\":true,\"bin\":\"${HOME}/.local/bin/tk\",\"skill\":\"${HOME}/.agents/skills/toolkit\",\"hooksPath\":\"${hooks_path}\",\"check\":${check_out}}"
else
    printf '%s\n' "{\"installed\":true,\"bin\":\"${HOME}/.local/bin/tk\",\"skill\":\"${HOME}/.agents/skills/toolkit\",\"check\":${check_out}}"
fi
