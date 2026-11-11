#!/usr/bin/env bash
#
# Prepare a freshly created git worktree for local hooks and pre-push checks.
#
# Keep this idempotent: every command should be safe to run more than once in
# the same checkout.

set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"

RESET="" INFO="" WARN="" ERR=""
if [[ -t 1 && ${CI:-false} != "true" ]]; then
	INFO=$'\e[1;34m'
	WARN=$'\e[1;33m'
	ERR=$'\e[1;31m'
	RESET=$'\e[0m'
fi

log() { printf "%s[INFO ]%s %s\n" "$INFO" "$RESET" "$*"; }
warn() { printf "%s[WARN ]%s %s\n" "$WARN" "$RESET" "$*" >&2; }
error() { printf "%s[ERROR]%s %s\n" "$ERR" "$RESET" "$*" >&2; }

die() {
	error "$1"
	exit "${2:-70}"
}

need() {
	command -v "$1" >/dev/null 2>&1 || die "'$1' not found" 69
}

trap 'error "Failure on or near line $LINENO"; exit 70' ERR
trap 'log "completed in ${SECONDS}s"' EXIT

export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/share/mise/shims:$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
export COREPACK_ENABLE_DOWNLOAD_PROMPT=0
export COREPACK_HOME="${COREPACK_HOME:-/private/tmp/configs-corepack-${USER:-codex}}"

usage() {
	cat <<'USAGE'
Usage: scripts/prepare-worktree.sh [options]

Prepare a freshly created git worktree for local hooks and pre-push checks.

Options:
  --force-install   Run dependency install even if node_modules already exists
  -h, --help        Show this help text
USAGE
}

force_install=0
while (( $# > 0 )); do
	case "$1" in
		--force-install)
			force_install=1
			shift
			;;
		-h|--help)
			usage
			exit 0
			;;
		*)
			error "unknown argument: $1"
			usage >&2
			exit 2
			;;
	esac
done

cd_repo_root() {
	need git
	cd "$REPO_ROOT"

	if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
		die "not inside a git work tree"
	fi
}

check_git_metadata_authority() {
	log "checking Git metadata authority"
	python3 codex/scripts/git-metadata-preflight.py --repo-root "$REPO_ROOT" --json
}

setup_mise() {
	local -a configs=()
	local config

	if ! command -v mise >/dev/null 2>&1; then
		warn "mise not found; skipping mise trust and activation"
		return
	fi

	[[ -f .mise.toml ]] && configs+=(.mise.toml)
	[[ -f mise.toml ]] && configs+=(mise.toml)
	[[ -f mise/config.toml ]] && configs+=(mise/config.toml)

	if (( ${#configs[@]} == 0 )); then
		warn "no mise config found; skipping mise trust"
	else
		for config in "${configs[@]}"; do
			log "trusting $config"
			mise trust --yes "$config"
		done
	fi

	eval "$(mise env -s bash)"
}

setup_node() {
	local -a pnpm_cmd

	if [[ ! -f package.json ]]; then
		warn "package.json not found; skipping Node setup"
		return
	fi

	if [[ ! -f pnpm-lock.yaml ]]; then
		warn "pnpm-lock.yaml not found; skipping deterministic pnpm install"
		return
	fi

	need node

	mkdir -p "$COREPACK_HOME"

	if command -v pnpm >/dev/null 2>&1; then
		pnpm_cmd=(pnpm)
	else
		need corepack
		pnpm_cmd=(corepack pnpm)
	fi

	if [[ "$force_install" -eq 1 || ! -d node_modules ]]; then
		log "installing Node dependencies"
		"${pnpm_cmd[@]}" install --frozen-lockfile
	else
		log "node_modules already present; skipping install"
	fi
}

setup_git_hooks() {
	if [[ ! -f scripts/setup-git-hooks.js ]]; then
		warn "scripts/setup-git-hooks.js not found; skipping git hook setup"
		return
	fi

	need node
	log "syncing git hooks"
	node scripts/setup-git-hooks.js
}

main() {
	cd_repo_root
	log "repo: $REPO_ROOT"
	setup_mise
	check_git_metadata_authority
	setup_node
	setup_git_hooks
	log "ready"
	log "next: bash scripts/verify-work.sh --fast"
}

main "$@"
