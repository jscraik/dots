#!/usr/bin/env bash
# Shared sandbox-safe cache/state setup for the configs git-hook adapters.
#
# Git metadata belongs under .git and is guarded separately. Hook caches and
# logs must stay outside .git so a hook cannot turn a cache write into a
# linked-worktree index.lock failure.

: "${repo_root:?repo_root must be set by the calling hook}"

canonicalize_path() {
	python3 -I - "$1" <<'PY'
from pathlib import Path
import sys

print(Path(sys.argv[1]).expanduser().resolve(strict=False))
PY
}

git_metadata_path() {
	local value
	value="$(
		env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE -u GIT_COMMON_DIR \
			git -C "$repo_root" rev-parse "$1" 2>/dev/null
	)" || return 1
	if [[ "$value" != /* ]]; then
		value="$repo_root/$value"
	fi
	canonicalize_path "$value"
}

path_contains() {
	local candidate="$1"
	local parent="$2"
	case "$candidate/" in
		"$parent/"*) return 0 ;;
		*) return 1 ;;
	esac
}

reject_git_metadata_cache_path() {
	local label="$1"
	local candidate="$2"
	local canonical
	canonical="$(canonicalize_path "$candidate")" || return 1
	if path_contains "$canonical" "$git_dir" || path_contains "$canonical" "$git_common_dir"; then
		printf '[hook-runtime-env] %s must stay outside Git metadata: %s\n' "$label" "$canonical" >&2
		return 78
	fi
	printf '%s' "$canonical"
}

repo_key="$(printf '%s' "$repo_root" | cksum | awk '{print $1}')"
git_dir="$(git_metadata_path --git-dir)" || {
	printf '[hook-runtime-env] unable to resolve Git metadata directory\n' >&2
	exit 78
}
git_common_dir="$(git_metadata_path --git-common-dir)" || {
	printf '[hook-runtime-env] unable to resolve Git common directory\n' >&2
	exit 78
}

hook_cache_candidate="${CODEX_HOOK_CACHE_ROOT:-}"
if [[ -z "$hook_cache_candidate" ]]; then
	if [[ -n "${HOME:-}" ]]; then
		home_root="$(canonicalize_path "$HOME")" || exit 78
		hook_cache_candidate="$home_root/.cache/codex-runtimes/configs-hook-cache-$(id -u)/$repo_key"
	else
		hook_cache_candidate="${TMPDIR:-/tmp}/configs-hook-cache-$(id -u)/$repo_key"
	fi
fi
cache_guard="$repo_root/scripts/cache_security.py"
guard_directory() {
	if [[ -r "$cache_guard" ]]; then
		python3 -I "$cache_guard" directory "$1"
		return
	fi
	# The installed shim embeds the guard so a staged helper deletion cannot
	# disable the repository hook it dispatches to. An older shim fails closed.
	local hook_guard
	hook_guard="$(
		env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE -u GIT_COMMON_DIR \
			git -C "$repo_root" rev-parse --git-path hooks/pre-commit
	)" || return 78
	if [[ "$hook_guard" != /* ]]; then
		hook_guard="$repo_root/$hook_guard"
	fi
	if [[ ! -x "$hook_guard" ]] || ! grep -Fq '# configs embedded cache guard v1' "$hook_guard"; then
		printf '[hook-runtime-env] installed cache guard is unavailable\n' >&2
		return 78
	fi
	"$hook_guard" --configs-cache-guard directory "$1"
}
hook_cache_root="$(canonicalize_path "$hook_cache_candidate")" || {
	printf '[hook-runtime-env] unable to canonicalize hook cache root: %s\n' "$hook_cache_candidate" >&2
	exit 78
}
if path_contains "$hook_cache_root" "$git_dir" || path_contains "$hook_cache_root" "$git_common_dir"; then
	printf '[hook-runtime-env] hook cache root must stay outside Git metadata: %s\n' "$hook_cache_root" >&2
	exit 78
fi
guard_directory "$hook_cache_candidate" || exit 78
if [[ ! -d "$hook_cache_root" || ! -w "$hook_cache_root" ]]; then
	printf '[hook-runtime-env] hook cache root is not writable: %s\n' "$hook_cache_root" >&2
	exit 78
fi

xdg_cache_home="$(reject_git_metadata_cache_path XDG_CACHE_HOME "${XDG_CACHE_HOME:-$hook_cache_root/xdg}")" || exit 78
pip_cache_dir="$(reject_git_metadata_cache_path PIP_CACHE_DIR "${PIP_CACHE_DIR:-$hook_cache_root/pip}")" || exit 78

export CODEX_HOOK_CACHE_ROOT="$hook_cache_root"
guard_directory "${XDG_CACHE_HOME:-$hook_cache_root/xdg}" || exit 78
guard_directory "${PIP_CACHE_DIR:-$hook_cache_root/pip}" || exit 78
export PREK_HOME="$hook_cache_root/prek"
export XDG_CACHE_HOME="$xdg_cache_home"
export PIP_CACHE_DIR="$pip_cache_dir"
# Keep scan output on stdout/stderr; mutable log paths cannot be bound through use.
export SEMGREP_LOG_FILE=/dev/null
export MISE_TRUSTED_CONFIG_PATHS="${MISE_TRUSTED_CONFIG_PATHS:-$repo_root/mise/config.toml:$repo_root/.mise.toml}"
