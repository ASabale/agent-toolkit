#!/bin/sh
# Idempotent install: symlink tk and the toolkit skill into the user paths,
# and configure git to use tracked hooks from .githooks/ when inside a git work tree.
set -eu
REPO_ROOT=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
SKILL_SRC="${REPO_ROOT}/skills/toolkit"
skill_links=""
skill_links_skipped=""

json_escape() {
    out=
    bytes=$(printf '%s' "$1" | od -An -tu1)
    for ord in $bytes; do
        case $ord in
            34) out="${out}\\\"" ;;
            92) out="${out}\\\\" ;;
            9) out="${out}\\t" ;;
            10) out="${out}\\n" ;;
            13) out="${out}\\r" ;;
            *)
                if [ "$ord" -lt 32 ]; then
                    out="${out}$(printf '\\u%04x' "$ord")"
                else
                    out="${out}$(printf "\\$(printf '%03o' "$ord")")"
                fi
                ;;
        esac
    done
    printf '%s' "$out"
}

append_link() {
    escaped=$(json_escape "$1")
    if [ -n "$skill_links" ]; then
        skill_links="${skill_links},\"${escaped}\""
    else
        skill_links="\"${escaped}\""
    fi
}

append_skipped() {
    path_json=$(json_escape "$1")
    reason_json=$(json_escape "$2")
    item="{\"path\":\"${path_json}\",\"reason\":\"${reason_json}\"}"
    if [ -n "$skill_links_skipped" ]; then
        skill_links_skipped="${skill_links_skipped},${item}"
    else
        skill_links_skipped=$item
    fi
}

dir_listed() {
    needle=$1
    list=$2
    [ -n "$list" ] || return 1
    printf '%s\n' "$list" | grep -F -x -- "$needle" >/dev/null 2>&1
}

add_skill_dir() {
    dir=$1
    [ -n "$dir" ] || return 0
    if dir_listed "$dir" "$skill_dirs"; then
        return 0
    fi
    if [ -n "$skill_dirs" ]; then
        skill_dirs="${skill_dirs}
${dir}"
    else
        skill_dirs=$dir
    fi
}

link_skill() {
    dest_parent=$1
    dest="${dest_parent}/toolkit"
    if [ -e "$dest" ] && [ ! -L "$dest" ]; then
        if [ -d "$dest" ]; then
            append_skipped "$dest" "existing non-symlink directory"
        else
            append_skipped "$dest" "existing non-symlink"
        fi
        return 0
    fi
    mkdir -p "$dest_parent"
    ln -sfn "${SKILL_SRC}" "$dest"
    append_link "$dest"
}

mkdir -p "${HOME}/.local/bin"
ln -sfn "${REPO_ROOT}/tk" "${HOME}/.local/bin/tk"

skill_dirs=""
add_skill_dir "${HOME}/.agents/skills"
if [ -d "${HOME}/.claude" ]; then
    add_skill_dir "${HOME}/.claude/skills"
fi
rest=${TK_SKILL_DIRS:-}
while [ -n "$rest" ]; do
    case "$rest" in
        *:*)
            extra=${rest%%:*}
            rest=${rest#*:}
            ;;
        *)
            extra=$rest
            rest=
            ;;
    esac
    add_skill_dir "$extra"
done

while IFS= read -r dest_parent; do
    [ -n "$dest_parent" ] || continue
    link_skill "$dest_parent"
done <<EOF
${skill_dirs}
EOF

hooks_path=""
if git -C "${REPO_ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git -C "${REPO_ROOT}" config core.hooksPath .githooks
    hooks_path=".githooks"
fi
check_out=$("${REPO_ROOT}/tk" check --json)
bin_json=$(json_escape "${HOME}/.local/bin/tk")
skill_json=$(json_escape "${HOME}/.agents/skills/toolkit")
if [ -n "$hooks_path" ]; then
    hooks_json=$(json_escape "$hooks_path")
    printf '%s\n' "{\"installed\":true,\"bin\":\"${bin_json}\",\"skill\":\"${skill_json}\",\"skill_links\":[${skill_links}],\"skill_links_skipped\":[${skill_links_skipped}],\"hooksPath\":\"${hooks_json}\",\"check\":${check_out}}"
else
    printf '%s\n' "{\"installed\":true,\"bin\":\"${bin_json}\",\"skill\":\"${skill_json}\",\"skill_links\":[${skill_links}],\"skill_links_skipped\":[${skill_links_skipped}],\"check\":${check_out}}"
fi
