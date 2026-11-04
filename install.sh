#!/bin/sh
# Idempotent install: symlink tk and the agent-toolkit skill into the user paths.
# Does not change git core.hooksPath; prints the command to opt in.
set -eu
# shellcheck disable=SC1007 # empty CDPATH= prefix so cd ignores a caller CDPATH
REPO_ROOT=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
SKILL_SRC="${REPO_ROOT}/skills/agent-toolkit"
skill_links=""
skill_links_skipped=""

install_hint() {
    case $(uname -s) in
        Darwin) printf '%s' "brew install $1" ;;
        *) printf '%s' "sudo apt-get install -y $1" ;;
    esac
}

emit_diag() {
    err=$(json_escape "$1")
    why=$(json_escape "$2")
    fix=$(json_escape "$3")
    printf '%s\n' "{\"error\":\"${err}\",\"why\":\"${why}\",\"fix\":\"${fix}\"}" >&2
}

emit_note() {
    note=$(json_escape "$1")
    why=$(json_escape "$2")
    fix=$(json_escape "$3")
    printf '%s\n' "{\"note\":\"${note}\",\"why\":\"${why}\",\"fix\":\"${fix}\"}" >&2
}

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
                    # shellcheck disable=SC2059 # octal printf format emits one JSON byte
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

encode_dir() {
    out=
    bytes=$(printf '%s' "$1" | od -An -tu1)
    for ord in $bytes; do
        case $ord in
            92) out="${out}\\\\" ;;
            10) out="${out}\\n" ;;
            *)
                # shellcheck disable=SC2059 # octal printf format encodes one path byte
                out="${out}$(printf "\\$(printf '%03o' "$ord")")"
                ;;
        esac
    done
    printf '%s' "$out"
}

dir_listed() {
    needle=$1
    [ -s "$skill_dirs_file" ] || return 1
    grep -F -x -- "$needle" "$skill_dirs_file" >/dev/null 2>&1
}

add_skill_dir() {
    dir=$1
    [ -n "$dir" ] || return 0
    encoded=$(encode_dir "$dir")
    if dir_listed "$encoded"; then
        return 0
    fi
    printf '%s\n' "$encoded" >> "$skill_dirs_file"
}

link_skill() {
    dest_parent=$1
    dest="${dest_parent}/agent-toolkit"
    old_dest="${dest_parent}/toolkit"
    if [ -L "$old_dest" ]; then
        old_target=$(readlink "$old_dest")
        old_ours="${REPO_ROOT}/skills/toolkit"
        if [ "$old_target" = "$old_ours" ] || [ "$old_target" = "${SKILL_SRC}" ]; then
            rm -f "$old_dest"
        fi
    fi
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

if ! command -v python3 >/dev/null 2>&1; then
    emit_diag "python3_missing" "python3 is required to run tk" "$(install_hint python3)"
    exit 1
fi
if ! command -v gh >/dev/null 2>&1; then
    emit_diag "gh_missing" "gh is not on PATH; GitHub tools will fail" "$(install_hint gh)"
fi

mkdir -p "${HOME}/.local/bin"
ln -sfn "${REPO_ROOT}/tk" "${HOME}/.local/bin/tk"

skill_dirs_file=$(mktemp)
trap 'rm -f "$skill_dirs_file"' EXIT
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

while IFS= read -r encoded || [ -n "$encoded" ]; do
    [ -n "$encoded" ] || continue
    dest_parent=$(printf '%b' "$encoded"; printf x)
    dest_parent=${dest_parent%x}
    link_skill "$dest_parent"
done < "$skill_dirs_file"

if git -C "${REPO_ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    emit_note \
        "hooksPath_unchanged" \
        "default install does not change core.hooksPath" \
        "git -C \"${REPO_ROOT}\" config core.hooksPath .githooks"
fi
check_out=$("${REPO_ROOT}/tk" check --json)
bin_json=$(json_escape "${HOME}/.local/bin/tk")
skill_json=$(json_escape "${HOME}/.agents/skills/agent-toolkit")
printf '%s\n' "{\"installed\":true,\"bin\":\"${bin_json}\",\"skill\":\"${skill_json}\",\"skill_links\":[${skill_links}],\"skill_links_skipped\":[${skill_links_skipped}],\"check\":${check_out}}"
