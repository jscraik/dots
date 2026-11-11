#!/usr/bin/env bash

if [[ -z "${BASH_VERSION:-}" ]]; then
	printf 'pre-commit hook requires bash. Run: bash scripts/git-hooks/pre-commit.sh\n' >&2
	return 2 2>/dev/null || exit 2
fi

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
	printf 'pre-commit hook is CLI-only. Run: bash scripts/git-hooks/pre-commit.sh\n' >&2
	return 2
fi

set -euo pipefail

script_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd -P "$script_dir/../.." && pwd -P)"
cd "$repo_root"

# shellcheck source=hook-runtime-env.sh
source "$script_dir/hook-runtime-env.sh"

# Git legitimately holds the current index lock while invoking pre-commit.
# Manual wrapper/Makefile execution must still fail closed on every lock, so
# only the installed Git hook shim may opt into the current-index exception.
preflight_lock_arg=''
if [[ "${CODEX_PRE_COMMIT_FROM_GIT:-0}" == "1" ]]; then
	preflight_lock_arg='--allow-current-index-lock'
fi
if [[ -n "$preflight_lock_arg" ]]; then
	set -- "$preflight_lock_arg"
else
	set --
fi
python3 codex/scripts/git-metadata-preflight.py --repo-root "$repo_root" "$@" --json

aikido_node_cert="/Library/Application Support/AikidoSecurity/EndpointProtection/run/endpoint-protection-combined-ca.pem"
if [[ -z "${NODE_EXTRA_CA_CERTS:-}" && -r "$aikido_node_cert" ]]; then
	export NODE_EXTRA_CA_CERTS="$aikido_node_cert"
fi
unset aikido_node_cert

node scripts/scrub-aikido-shell-profile-snippets.mjs
pnpm lint
pnpm typecheck
pnpm run secrets:staged
pnpm run docs:style:changed
pnpm run test:related
