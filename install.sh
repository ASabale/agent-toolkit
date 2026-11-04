#!/bin/sh
# Idempotent install: symlink tk and the toolkit skill into the user paths.
set -eu
REPO_ROOT=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
mkdir -p "${HOME}/.local/bin" "${HOME}/.agents/skills"
ln -sfn "${REPO_ROOT}/tk" "${HOME}/.local/bin/tk"
ln -sfn "${REPO_ROOT}/skills/toolkit" "${HOME}/.agents/skills/toolkit"
check_out=$("${REPO_ROOT}/tk" check --json)
printf '%s\n' "{\"installed\":true,\"bin\":\"${HOME}/.local/bin/tk\",\"skill\":\"${HOME}/.agents/skills/toolkit\",\"check\":${check_out}}"
