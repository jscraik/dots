#!/usr/bin/env bash

if [[ -z "${BASH_VERSION:-}" ]]; then
	printf 'pre-push hook requires bash. Run: bash scripts/git-hooks/pre-push.sh\n' >&2
	return 2 2>/dev/null || exit 2
fi

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
	printf 'pre-push hook is CLI-only. Run: bash scripts/git-hooks/pre-push.sh\n' >&2
	return 2
fi

set -euo pipefail

script_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd -P "$script_dir/../.." && pwd -P)"
cd "$repo_root"

# shellcheck source=hook-runtime-env.sh
source "$script_dir/hook-runtime-env.sh"

python3 codex/scripts/git-metadata-preflight.py --repo-root "$repo_root" --json

node scripts/scrub-aikido-shell-profile-snippets.mjs
pnpm run semgrep:changed
pnpm build
