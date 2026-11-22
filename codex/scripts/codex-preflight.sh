#!/usr/bin/env bash

if [[ -z "${BASH_VERSION:-}" ]]; then
	printf '❌ codex-preflight.sh requires bash. Run: bash scripts/codex-preflight.sh [options]\n' >&2
	return 2 2>/dev/null || exit 2
fi

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
	printf '❌ codex-preflight.sh is CLI-only; do not source it. Run: bash scripts/codex-preflight.sh [options]\n' >&2
	return 2
fi

set -euo pipefail

dots_helper_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
python3 -I -S -B "$dots_helper_dir/admit-hook-fixture.py" '{}' || exit $?

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
WORKSPACE_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"

usage() {
	cat <<'USAGE'
Usage:
  ./scripts/codex-preflight.sh [options]

Options:
  --stack <auto|repo|js|py|rust>    Stack mode. Default: auto
  --mode <off|optional|required>    Retired option, accepted but ignored
  --repo-fragment <text>            Require repo root to contain this fragment
  --bins <csv>                      Override required binaries
  --paths <csv>                     Override required paths
  -h, --help                        Show this help

Examples:
  ./scripts/codex-preflight.sh
  ./scripts/codex-preflight.sh --stack js
  ./scripts/codex-preflight.sh --stack py
  ./scripts/codex-preflight.sh --repo-fragment configs

Legacy compatibility:
  ./scripts/codex-preflight.sh <repo-fragment> [bins-csv] [paths-csv]
  This preserves the older positional interface used by parent-repo checks and
  never starts or probes the retired Local Memory service.
USAGE
}

log_section() {
	printf '== %s ==\n' "$*"
}

log_ok() {
	printf '✅ %s\n' "$*"
}

log_warn() {
	printf '⚠️ %s\n' "$*"
}

log_err() {
	printf '❌ %s\n' "$*" >&2
}

detect_stack() {
	if [[ -f package.json ]]; then
		echo js
		return
	fi
	if [[ -f pyproject.toml ]]; then
		echo py
		return
	fi
	if [[ -f Cargo.toml ]]; then
		echo rust
		return
	fi
	echo repo
}

stack_bins_csv() {
	case "$1" in
		js) echo 'git,bash,sed,rg,fd,jq,curl,node,npm,python3' ;;
		py) echo 'git,bash,sed,rg,fd,jq,curl,python3' ;;
		rust) echo 'git,bash,sed,rg,fd,jq,curl,python3,cargo' ;;
		repo) echo 'git,bash,sed,rg,fd,jq,curl,python3' ;;
		*) log_err "unknown stack: $1"; return 2 ;;
	esac
}

stack_paths_csv() {
	case "$1" in
		js) echo 'AGENTS.md,package.json,instructions,scripts,rules' ;;
		py) echo 'AGENTS.md,pyproject.toml,instructions,scripts,rules' ;;
		rust) echo 'AGENTS.md,Cargo.toml,instructions,scripts,rules' ;;
		repo) echo 'AGENTS.md,instructions,scripts,rules' ;;
		*) log_err "unknown stack: $1"; return 2 ;;
	esac
}

check_bins() {
	local bins_csv="$1"
	local -a bins=()
	local -a missing_bins=()
	local b

	IFS=',' read -r -a bins <<<"${bins_csv}"
	for b in "${bins[@]}"; do
		[[ -z "${b}" ]] && continue
		if ! command -v "${b}" >/dev/null 2>&1; then
			missing_bins+=("${b}")
		fi
	done

	if (( ${#missing_bins[@]} > 0 )); then
		log_err "missing binaries: ${missing_bins[*]}"
		return 2
	fi
	log_ok "binaries ok: ${bins_csv}"
}

check_paths() {
	local root="$1"
	local paths_csv="$2"
	local -a paths=()
	local p

	IFS=',' read -r -a paths <<<"${paths_csv}"
	for p in "${paths[@]}"; do
		[[ -z "${p}" ]] && continue

		local -a matches=()
		local match
		shopt -s nullglob
		for match in ${p}; do
			matches+=("${match}")
		done
		shopt -u nullglob

		if (( ${#matches[@]} == 0 )); then
			matches+=("${p}")
		fi

		local found=0
		local abs
		for match in "${matches[@]}"; do
			if [[ -e "${match}" ]]; then
				found=1
				if ! abs="$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "${match}")"; then
					log_err "failed to resolve path: ${match}"
					return 2
				fi
				if [[ "${abs}" != "${root}" && "${abs}" != "${root}"/* ]]; then
					log_err "path escapes repo root: ${match} -> ${abs}"
					return 2
				fi
			fi
		done

		if (( found == 0 )); then
			log_err "missing path: ${p}"
			return 2
		fi
	done
	log_ok "paths ok: ${paths_csv}"
}

main() {
	local stack='auto'
	local local_memory_mode='required'
	local expected_repo=''
	local bins_csv=''
	local paths_csv=''

	if (( $# > 0 )) && [[ "${1}" != --* ]] && [[ "${1}" != '-h' ]]; then
		if (( $# > 3 )); then
			log_err "legacy positional mode accepts at most 3 arguments"
			usage >&2
			exit 2
		fi
		expected_repo="${1:-}"
		bins_csv="${2:-}"
		paths_csv="${3:-}"
		local_memory_mode='off'
		set --
	fi

	while (( $# > 0 )); do
		case "$1" in
			--stack)
				stack="${2:-}"
				shift 2
				;;
			--mode)
				local_memory_mode="${2:-}"
				shift 2
				;;
			--repo-fragment)
				expected_repo="${2:-}"
				shift 2
				;;
			--bins)
				bins_csv="${2:-}"
				shift 2
				;;
			--paths)
				paths_csv="${2:-}"
				shift 2
				;;
			-h|--help)
				usage
				exit 0
				;;
			*)
				log_err "unknown argument: $1"
				usage >&2
				exit 2
				;;
		esac
	done

	case "${local_memory_mode}" in
		off|optional|required) ;;
		*) log_err "invalid --mode: ${local_memory_mode}"; exit 2 ;;
	esac

	log_section 'Codex Preflight'
	echo "pwd: $(pwd)"

	if ! command -v git >/dev/null 2>&1; then
		log_err 'missing binary: git'
		exit 2
	fi

	local git_root
	if ! git_root="$(git rev-parse --show-toplevel 2>/dev/null)"; then
		log_err 'not inside a git repo (git rev-parse failed)'
		exit 2
	fi
	if [[ -z "${git_root}" ]]; then
		log_err 'git rev-parse returned empty root'
		exit 2
	fi
	git_root="$(cd -- "${git_root}" && pwd -P)"
	echo "git root: ${git_root}"
	echo "workspace root: ${WORKSPACE_ROOT}"

	if [[ "${WORKSPACE_ROOT}" != "${git_root}" && "${WORKSPACE_ROOT}" != "${git_root}"/* ]]; then
		log_err "script workspace mismatch: ${WORKSPACE_ROOT} is not inside git root ${git_root}"
		exit 2
	fi
	if [[ -n "${expected_repo}" && "${WORKSPACE_ROOT}" != *"${expected_repo}"* ]]; then
		log_err "repo mismatch: expected fragment '${expected_repo}' in '${WORKSPACE_ROOT}'"
		exit 2
	fi

	cd "${WORKSPACE_ROOT}"

	if [[ "${stack}" == 'auto' ]]; then
		stack="$(detect_stack)"
	fi
	echo "stack: ${stack}"

	if [[ -z "${bins_csv}" ]]; then
		bins_csv="$(stack_bins_csv "${stack}")"
	fi
	if [[ -z "${paths_csv}" ]]; then
		paths_csv="$(stack_paths_csv "${stack}")"
	fi

	check_bins "${bins_csv}"
	check_paths "${WORKSPACE_ROOT}" "${paths_csv}"

	echo "git branch: $(git -C "${WORKSPACE_ROOT}" rev-parse --abbrev-ref HEAD)"
	echo "clean?: $(git -C "${WORKSPACE_ROOT}" status --porcelain -- . | wc -l | tr -d ' ') changes"

	log_ok 'preflight passed'
}

main "$@"
