#!/usr/bin/env bash
# Local environment preflight (strict)
# Fails fast when required tooling is missing.

set -euo pipefail

prepend_standard_tool_paths() {
	local candidate
	for candidate in \
		"$HOME/.local/share/mise/shims" \
		"$HOME/.local/bin" \
		"/opt/homebrew/bin" \
		"/opt/homebrew/sbin" \
		"/usr/local/bin" \
		"/usr/sbin" \
		"/sbin"; do
		if [[ -d "$candidate" && ":$PATH:" != *":$candidate:"* ]]; then
			PATH="$candidate:$PATH"
		fi
	done
	export PATH
}

prepend_standard_tool_paths

if [[ "${BASH_VERSINFO[0]:-0}" -lt 4 && -z "${CHECK_ENVIRONMENT_REEXECED:-}" ]]; then
	if [[ -x "/opt/homebrew/bin/bash" ]]; then
		export CHECK_ENVIRONMENT_REEXECED=1
		exec "/opt/homebrew/bin/bash" "$0" "$@"
	elif [[ -x "/usr/local/bin/bash" ]]; then
		export CHECK_ENVIRONMENT_REEXECED=1
		exec "/usr/local/bin/bash" "$0" "$@"
	fi
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

# Homebrew can keep an installed formula or preview cask unlinked. Resolve the
# one required binary without mutating global Homebrew links or the caller's
# installation.
if ! command -v circleci >/dev/null 2>&1; then
	if circleci_bin="$(bash "$SCRIPT_DIR/resolve-homebrew-bin.sh" circleci 2>/dev/null)"; then
		PATH="${circleci_bin%/*}:$PATH"
		export PATH
	fi
fi

CONTRACT_PATH="$REPO_ROOT/harness.contract.json"
	ATTESTATION_PATH="$REPO_ROOT/artifacts/policy/environment-attestation.json"
	MISE_PATH="$REPO_ROOT/mise/config.toml"
	REPO_MISE_PATH="$REPO_ROOT/.mise.toml"
	BREWFILE_PATH="$REPO_ROOT/Brewfile"
	CODEX_ENVIRONMENT_PATH="$REPO_ROOT/codex/environments/environment.toml"
	MAKEFILE_PATH="$REPO_ROOT/Makefile"
	PREK_CONFIG_PATH="$REPO_ROOT/prek.toml"
	PACKAGE_JSON_PATH="$REPO_ROOT/package.json"
	CODESTYLE_PATH="$REPO_ROOT/CODESTYLE.md"
	TOOLING_DOC_PATH="${TOOLING_DOC_PATH:-$REPO_ROOT/codex/instructions/tooling.md}"

if [[ ! -f "$CONTRACT_PATH" ]]; then
	echo "Error: missing contract file at $CONTRACT_PATH"
	exit 1
fi

if ! command -v rg >/dev/null 2>&1; then
	echo "Error: required binary 'rg' is not installed or not on PATH"
	exit 1
fi

	if [[ ! -f "$MISE_PATH" ]]; then
		echo "Error: missing mise config at $MISE_PATH"
		exit 1
	fi

	if [[ ! -f "$REPO_MISE_PATH" ]]; then
		echo "Error: missing repository mise config at $REPO_MISE_PATH"
		exit 1
	fi

	if [[ ! -f "$BREWFILE_PATH" ]]; then
		echo "Error: missing Brewfile at $BREWFILE_PATH"
		exit 1
	fi

	if [[ ! -f "$CODEX_ENVIRONMENT_PATH" ]]; then
		echo "Error: missing Codex environment file at $CODEX_ENVIRONMENT_PATH"
		exit 1
	fi

	if [[ ! -f "$MAKEFILE_PATH" ]]; then
		echo "Error: missing required Makefile at $MAKEFILE_PATH"
		exit 1
	fi

	if [[ ! -f "$PREK_CONFIG_PATH" ]]; then
		echo "Error: missing required prek config at $PREK_CONFIG_PATH"
		exit 1
	fi

	if [[ ! -f "$CODESTYLE_PATH" ]]; then
		echo "Error: missing CODESTYLE contract at $CODESTYLE_PATH"
		exit 1
	fi

	required_support_files=("scripts/codex-preflight.sh" "scripts/new-task.sh" "scripts/validate-commit-msg.js" "scripts/check-staged-secrets.sh" "scripts/check-doc-style.sh" "scripts/check-related-tests.sh" "scripts/check-semgrep-changed.sh" "scripts/semgrep-pre-push.yml" "scripts/git-hooks/hook-runtime-env.sh" "scripts/resolve-homebrew-bin.sh" "codex/scripts/git-metadata-preflight.py" "codex/scripts/verify-work.sh" "codex/scripts/validate-instruction-routing.py")
	for support_file in "${required_support_files[@]}"; do
		if [[ ! -f "$REPO_ROOT/${support_file}" ]]; then
			echo "Error: missing required hook support file at $REPO_ROOT/${support_file}"
			exit 1
		fi
	done

	project_brain_memory_extension_enabled=false
	required_project_brain_paths=(".harness/memory/LEARNINGS.md" ".harness/knowledge/INDEX.md" ".harness/knowledge/cli/knowledge.md" ".harness/knowledge/cli/hypotheses.md" ".harness/knowledge/cli/rules.md" ".harness/knowledge/ci/knowledge.md" ".harness/knowledge/ci/hypotheses.md" ".harness/knowledge/ci/rules.md" ".harness/knowledge/governance/knowledge.md" ".harness/knowledge/governance/hypotheses.md" ".harness/knowledge/governance/rules.md" ".harness/knowledge/tooling/knowledge.md" ".harness/knowledge/tooling/hypotheses.md" ".harness/knowledge/tooling/rules.md" ".harness/knowledge/tooling/codex-learn-summary.md" ".harness/decisions" ".harness/quality/criteria.md" ".harness/review-log.md")
	if [[ -e "$REPO_ROOT/.harness/memory/LEARNINGS.md" || -e "$REPO_ROOT/.harness/knowledge/INDEX.md" || -d "$REPO_ROOT/.harness/knowledge" ]]; then
		project_brain_memory_extension_enabled=true
	fi
	if [[ "$project_brain_memory_extension_enabled" == "true" ]]; then
		for required_path in "${required_project_brain_paths[@]}"; do
			if [[ ! -e "$REPO_ROOT/${required_path}" ]]; then
				echo "Error: required Project Brain memory-extension path '$required_path' is missing under $REPO_ROOT"
				echo "Fix: run harness init --update to restore Project Brain scaffolding."
				exit 1
			fi
		done
	fi

if ! command -v mise >/dev/null 2>&1; then
	echo "Error: required binary 'mise' is not installed or not on PATH"
	exit 1
fi

# Bootstrap the full repo-managed environment so hook validation reflects the
# pinned runtime versions and required approval posture, not only the caller
# shell's PATH.
eval "$(mise activate bash)"
export CODEX_APPROVAL_POSTURE="${CODEX_APPROVAL_POSTURE:-require}"

required_mise_tools=("node" "pnpm" "python" "uv" "cargo:prek" "npm:@brainwav/diagram" "npm:@argos-ci/cli" "cosign" "cloudflared" "npm:vitest" "ruff" "npm:eslint" "npm:@mermaid-js/mermaid-cli" "npm:@brainwav/rsearch" "npm:@brainwav/wsearch-cli" "npm:beautiful-mermaid" "npm:markdownlint-cli2" "npm:semver" "npm:wrangler" "npm:portless" "semgrep" "trivy" "vale" "betterleaks")
for tool in "${required_mise_tools[@]}"; do
	tool_pattern="$(printf '%s' "$tool" | sed 's/[][(){}.^$*+?|\\]/\\&/g')"
	if ! rg -q "^[[:space:]]*(\"${tool_pattern}\"|${tool_pattern})[[:space:]]*=" "$MISE_PATH"; then
		echo "Error: required tool '$tool' is not pinned in $MISE_PATH [tools]"
		echo "Fix: add '$tool = \"<version>\"' to $MISE_PATH."
		exit 1
	fi
done

required_repo_mise_tools=("npm:agent-browser" "npm:agentation" "npm:agentation-mcp")
for tool in "${required_repo_mise_tools[@]}"; do
	tool_pattern="$(printf '%s' "$tool" | sed 's/[][(){}.^$*+?|\\]/\\&/g')"
	if ! rg -q "^[[:space:]]*(\"${tool_pattern}\"|${tool_pattern})[[:space:]]*=" "$REPO_MISE_PATH"; then
		echo "Error: required browser tool '$tool' is not pinned in $REPO_MISE_PATH [tools]"
		echo "Fix: add '$tool = \"<version>\"' to $REPO_MISE_PATH."
		exit 1
	fi
done

if [[ -f "$TOOLING_DOC_PATH" ]]; then
	# This document is a routing contract, not a second package inventory. Keep
	# source-of-truth and diagnostic concepts discoverable while validating the
	# actual tool names against mise, Brewfile, and executable state below.
	required_tooling_doc_terms=("package.json" "lockfile" ".mise.toml" "mise/config.toml" "Brewfile" "package manager" "command -v" "codex mcp" "mcp-startup-triage" "agent-browser" "agentation" "browser-evidence-artifacts")
	for term in "${required_tooling_doc_terms[@]}"; do
		if ! rg -Fqi -- "$term" "$TOOLING_DOC_PATH"; then
			echo "Error: tooling doc missing expected term '$term': $TOOLING_DOC_PATH"
			echo "Fix: restore the durable source-of-truth or diagnostic route."
			echo "Interactive flow: run a Codex AskQuestion/request_user_input prompt before applying installs."
			exit 1
		fi
	done
else
	echo "Error: tooling doc not found at $TOOLING_DOC_PATH"
	exit 1
fi

	required_bins=("pnpm" "node" "jq" "make" "rg" "fd" "prek" "diagram" "mise" "vale" "argos" "cosign" "cloudflared" "vitest" "ruff" "eslint" "agent-browser" "agentation-mcp" "mmdc" "markdownlint-cli2" "wrangler" "portless" "beautiful-mermaid" "semgrep" "semver" "trivy" "betterleaks" "gitleaks" "rsearch" "wsearch" "pdftotext" "pdfinfo" "pdftoppm" "pdfimages" "tesseract" "ocrmypdf" "unpaper" "qpdf" "gs" "magick" "pandoc" "doctl" "infisical" "mole" "mosh" "circleci")
	optional_bins=("mitmproxy" "ghidraRun")
	for bin in "${required_bins[@]}"; do
		if ! command -v "$bin" >/dev/null 2>&1; then
			echo "Error: required binary '$bin' is not installed or not on PATH"
			exit 1
		fi
	done
	for bin in "${optional_bins[@]}"; do
		if ! command -v "$bin" >/dev/null 2>&1; then
			echo "Warning: optional binary '$bin' is not installed or not on PATH"
		fi
	done

	required_python_document_modules=("defusedxml" "PIL" "pypdf" "pdfminer" "fitz" "pdf2image" "pytesseract" "cv2" "numpy")
	for module in "${required_python_document_modules[@]}"; do
		if ! python3 - "$module" <<'PY'
import importlib.util
import sys

module_name = sys.argv[1]
if importlib.util.find_spec(module_name) is None:
    raise SystemExit(1)
PY
		then
			echo "Error: required Python document/OCR/image module '$module' is not importable from the active mise Python"
			echo "Fix: run 'eval \"\$(mise activate zsh)\" && python3 -m pip install --user -r requirements/python-document-reading.txt'."
			exit 1
		fi
	done

	if ! HOMEBREW_NO_AUTO_UPDATE=1 brew bundle check --global --verbose >/dev/null; then
		echo "Error: Brewfile dependencies are not satisfied"
		echo "Fix: run 'HOMEBREW_NO_AUTO_UPDATE=1 brew bundle --global'."
		exit 1
	fi

	required_codex_actions=("Tools|tool" "Run|run" "Debug|debug" "Test|test" "Prek|test" "Release Finalize|tool" "Diagram|tool" "Ralph|debug" "Mise|tool" "Brew Bundle|tool" "Vale|debug" "Argos|test" "Cosign|debug" "Cloudflared|run" "Vitest|test" "Ruff|debug" "ESLint|debug" "Agent Browser|tool" "Agentation|tool" "Mermaid CLI|tool" "MarkdownLint|debug" "Wrangler|run" "1Password|tool" "Beautiful Mermaid|tool" "Auth0|tool" "Semgrep|debug" "Semver|tool" "Trivy|debug" "Betterleaks|debug" "Gitleaks|debug" "PDF Text|tool" "OCR PDF|tool" "ImageMagick|tool" "Pandoc|tool" "DigitalOcean|tool" "Infisical|tool" "Mosh|tool" "CircleCI|tool" "Ghidra|tool" "Mitmproxy|tool" "Research|tool" "WSearch|tool")
	for action in "${required_codex_actions[@]}"; do
		name="${action%%|*}"
		icon="${action##*|}"
		if ! awk -v name="$name" -v icon="$icon" '
			prev == "name = \"" name "\"" && $0 == "icon = \"" icon "\"" { found = 1 }
			{ prev = $0 }
			END { exit found ? 0 : 1 }
		' "$CODEX_ENVIRONMENT_PATH"; then
			echo "Error: Codex environment action '$name' is missing or mapped to the wrong icon in $CODEX_ENVIRONMENT_PATH"
			exit 1
		fi
	done

	required_make_targets=("help" "install" "setup" "preflight" "worktree-ready" "verify-work" "codestyle" "hooks" "hooks-pre-commit" "hooks-pre-push" "hooks-commit-msg" "secrets-staged" "docs-style-changed" "related-tests" "semgrep-changed" "diagrams-check" "lint" "docs-lint" "fmt" "typecheck" "test" "check" "audit" "secrets" "security" "clean" "reset" "ci" "diagrams" "env-check")
	for target in "${required_make_targets[@]}"; do
		if ! rg -q "^${target}:" "$MAKEFILE_PATH"; then
			echo "Error: required Makefile target '$target' is missing from $MAKEFILE_PATH"
			exit 1
		fi
	done

	python3 - "$PREK_CONFIG_PATH" <<'PY'
import sys
import tomllib

prek_config_path = sys.argv[1]
with open(prek_config_path, "rb") as config_file:
    prek_config = tomllib.load(config_file)

expected_hooks = {
    "pre-commit": {
        "name": "Pre-commit",
        "entry": "bash scripts/git-hooks/pre-commit.sh",
        "language": "system",
        "pass_filenames": False,
    },
    "pre-push": {
        "name": "Pre-push",
        "entry": "bash scripts/git-hooks/pre-push.sh",
        "language": "system",
        "pass_filenames": False,
        "stages": ["pre-push"],
    },
}
blocked_fragments = (
    "make hooks-pre-commit",
    "make hooks-pre-push",
    "make hooks-commit-msg",
    "gmake hooks-pre-commit",
    "gmake hooks-pre-push",
    "gmake hooks-commit-msg",
    "$(MAKE) hooks-pre-commit",
    "$(MAKE) hooks-pre-push",
    "$(MAKE) hooks-commit-msg",
    "pre-commit run",
    "prek run",
    ".git/hooks/",
    "hook-impl",
)

hooks = {}
for repo in prek_config.get("repos", []):
    for hook in repo.get("hooks", []):
        hook_id = hook.get("id")
        if isinstance(hook_id, str):
            hooks[hook_id] = hook

for hook_id, expected in expected_hooks.items():
    hook = hooks.get(hook_id)
    if hook is None:
        raise SystemExit(f"Error: required prek hook '{hook_id}' is missing from {prek_config_path}")
    for key, expected_value in expected.items():
        actual_value = hook.get(key)
        if actual_value != expected_value:
            raise SystemExit(
                f"Error: required prek hook '{hook_id}' is out of date in {prek_config_path}: "
                f"{key} should be {expected_value!r}, got {actual_value!r}"
            )

for hook_id, hook in hooks.items():
    entry = hook.get("entry")
    if not isinstance(entry, str):
        continue
    for fragment in blocked_fragments:
        if fragment in entry:
            raise SystemExit(
                "Error: prek hook entries must call leaf scripts, not nested hook orchestration. "
                f"Hook '{hook_id}' entry contains blocked fragment {fragment!r}. "
                "Fix: use scripts/git-hooks/* leaf adapters for installed hooks; "
                "keep make hooks-* as top-level operator commands."
            )
PY

	if [[ -d "$REPO_ROOT/scripts/git-hooks" ]] && rg -n -F \
		-e "make hooks-pre-commit" \
		-e "make hooks-pre-push" \
		-e "make hooks-commit-msg" \
		-e "gmake hooks-pre-commit" \
		-e "gmake hooks-pre-push" \
		-e "gmake hooks-commit-msg" \
		-e "\$(MAKE) hooks-pre-commit" \
		-e "\$(MAKE) hooks-pre-push" \
		-e "\$(MAKE) hooks-commit-msg" \
		-e "pre-commit run" \
		-e "prek run" \
		-e ".git/hooks/" \
		-e "hook-impl" \
		"$REPO_ROOT/scripts/git-hooks"; then
		echo "Error: git hook leaf scripts must not invoke nested hook orchestration." >&2
		echo "Fix: call explicit validators or shared leaf scripts instead of make hooks-*, pre-commit run, prek run, or .git/hooks/*." >&2
		exit 1
	fi

	if [[ -f "$PACKAGE_JSON_PATH" ]]; then
		required_package_scripts=("secrets:staged|bash scripts/check-staged-secrets.sh" "docs:style:changed|bash scripts/check-doc-style.sh" "test:related|bash scripts/check-related-tests.sh" "semgrep:changed|bash scripts/check-semgrep-changed.sh")
		for script_spec in "${required_package_scripts[@]}"; do
			script_name="${script_spec%%|*}"
			script_command="${script_spec#*|}"
			if ! jq -e --arg script_name "$script_name" --arg script_command "$script_command" '
				(.scripts // {})[$script_name] == $script_command
			' "$PACKAGE_JSON_PATH" >/dev/null; then
				echo "Error: package script '$script_name' is missing or out of date in $PACKAGE_JSON_PATH"
				echo "Fix: run node scripts/setup-git-hooks.js"
				exit 1
			fi
		done

		if jq -e 'has("simple-git-hooks")' "$PACKAGE_JSON_PATH" >/dev/null; then
			echo "Error: legacy simple-git-hooks config must be removed from $PACKAGE_JSON_PATH"
			echo "Fix: delete the simple-git-hooks package/config and use node scripts/setup-git-hooks.js to install prek hooks."
			exit 1
		fi

		has_package_marker() {
			local marker="$1"
			jq -e --arg marker "$marker" '
				((.dependencies // {}) + (.devDependencies // {})) | has($marker)
			' "$PACKAGE_JSON_PATH" >/dev/null
		}

		repo_capabilities=()
		explicit_capabilities=()
		if ((${#explicit_capabilities[@]} > 0)); then
			for capability in "${explicit_capabilities[@]}"; do
				[[ -n "$capability" ]] || continue
				repo_capabilities+=("$capability")
			done
		fi
		ui_markers=("react" "react-dom" "next" "vite" "tailwindcss" "@storybook/react" "@storybook/react-vite" "@radix-ui/react-slot")
		for marker in "${ui_markers[@]}"; do
			if has_package_marker "$marker"; then
				repo_capabilities+=("ui")
				break
			fi
		done

		chatgpt_apps_sdk_markers=("@openai/chatkit" "@openai/agents" "@openai/agents-realtime")
		for marker in "${chatgpt_apps_sdk_markers[@]}"; do
			if has_package_marker "$marker"; then
				repo_capabilities+=("chatgpt_apps_sdk")
				break
			fi
		done

		# has_capability checks whether the repository lists a specific capability in the `repo_capabilities` array.
		has_capability() {
			local wanted="$1"
			if ((${#repo_capabilities[@]} > 0)); then
				for capability in "${repo_capabilities[@]}"; do
					if [[ "$capability" == "$wanted" ]]; then
						return 0
					fi
				done
			fi
			return 1
		}

		# has_required_package checks whether PACKAGE_JSON_PATH contains the
		# given package in the specified dependency set ('dependencies',
		# 'devDependencies' or 'either').
		has_required_package() {
			local pkg="$1"
			local dependency_type="$2"
			case "$dependency_type" in
				dependencies)
					jq -e --arg pkg "$pkg" '(.dependencies // {}) | has($pkg)' "$PACKAGE_JSON_PATH" >/dev/null
					;;
				devDependencies)
					jq -e --arg pkg "$pkg" '(.devDependencies // {}) | has($pkg)' "$PACKAGE_JSON_PATH" >/dev/null
					;;
				either)
					jq -e --arg pkg "$pkg" '((.dependencies // {}) | has($pkg)) or ((.devDependencies // {}) | has($pkg))' "$PACKAGE_JSON_PATH" >/dev/null
					;;
				*)
					return 1
					;;
			esac
		}

		# has_required_package_or_global_tool checks whether a package is
		# present in package.json for the given dependency type or, for
		# @brainwav/design-system-guidance, is satisfied by a globally
		# installed `design-system-guidance` CLI.
		has_required_package_or_global_tool() {
			local pkg="$1"
			local dependency_type="$2"
			if has_required_package "$pkg" "$dependency_type"; then
				return 0
			fi
			if [[ "$pkg" == "@brainwav/design-system-guidance" ]] && command -v design-system-guidance >/dev/null 2>&1; then
				return 0
			fi
			return 1
		}

		required_package_specs=("@brainwav/design-system-guidance|either|ui,chatgpt_apps_sdk")
		for spec in "${required_package_specs[@]}"; do
			pkg="${spec%%|*}"
			rest="${spec#*|}"
			dependency_type="${rest%%|*}"
			required_caps_csv="${rest#*|}"
			should_apply=0
			IFS=',' read -r -a required_caps <<< "$required_caps_csv"
			for capability in "${required_caps[@]}"; do
				if has_capability "$capability"; then
					should_apply=1
					break
				fi
		done
			if [[ "$should_apply" -eq 1 ]] && ! has_required_package_or_global_tool "$pkg" "$dependency_type"; then
				echo "Error: required package '$pkg' is missing from $PACKAGE_JSON_PATH for explicit or detected UI/App SDK capabilities"
				echo "Fix: npm i $pkg"
				exit 1
			fi
		done
	fi

	mkdir -p "$REPO_ROOT/artifacts/policy"

echo "Running harness environment preflight..."

run_check_environment_with_runner() {
	local label="$1"
	shift
	local -a runner=("$@")
	local output=""
	local exit_code=0

	rm -f "$ATTESTATION_PATH"

	echo "Using harness runner: $label"
	set +e
	output="$("${runner[@]}" check-environment \
		--contract "$CONTRACT_PATH" \
		--json \
		--attestation "$ATTESTATION_PATH" 2>&1)"
	exit_code=$?
	set -e

	if [[ -n "$output" ]]; then
		printf '%s\n' "$output"
	fi

	if [[ "$exit_code" -ne 0 ]]; then
		echo "Runner failed: $label (exit $exit_code)"
		return 1
	fi

	if [[ ! -f "$ATTESTATION_PATH" ]]; then
		local json_line
		json_line="$(printf '%s\n' "$output" | awk '/^\{/{line=$0} END{if(line!="") print line}')"
		if [[ -n "$json_line" ]]; then
			printf '%s\n' "$json_line" > "$ATTESTATION_PATH"
		fi
	fi

	if [[ ! -f "$ATTESTATION_PATH" ]]; then
		echo "Runner produced no attestation output: $label"
		return 1
	fi

	return 0
}

runner_ok=1

if [[ -f "$REPO_ROOT/src/cli.ts" ]] && command -v pnpm >/dev/null 2>&1; then
	if run_check_environment_with_runner "repo source CLI (pnpm exec tsx src/cli.ts)" pnpm exec tsx "$REPO_ROOT/src/cli.ts"; then
		runner_ok=0
	else
		echo "Warning: repo source CLI failed; trying fallback runners."
	fi
fi

if [[ "$runner_ok" -ne 0 && -f "$REPO_ROOT/dist/cli.js" ]] && command -v node >/dev/null 2>&1; then
	if run_check_environment_with_runner "repo dist CLI (node dist/cli.js)" node "$REPO_ROOT/dist/cli.js"; then
		runner_ok=0
	else
		echo "Warning: repo dist CLI failed; trying fallback runners."
	fi
fi

if [[ "$runner_ok" -ne 0 && -x "$REPO_ROOT/node_modules/.bin/harness" ]]; then
	if run_check_environment_with_runner "repo dependency harness ($REPO_ROOT/node_modules/.bin/harness)" "$REPO_ROOT/node_modules/.bin/harness"; then
		runner_ok=0
	else
		echo "Warning: repo dependency harness failed; trying fallback runners."
	fi
fi

if [[ "$runner_ok" -ne 0 && -r "$REPO_ROOT/scripts/harness-cli.sh" ]]; then
	if run_check_environment_with_runner "repo wrapper (bash scripts/harness-cli.sh)" bash "$REPO_ROOT/scripts/harness-cli.sh"; then
		runner_ok=0
	else
		echo "Warning: repo wrapper failed; trying fallback runners."
	fi
fi

if [[ "$runner_ok" -ne 0 ]]; then
	mise_harness_bin=""
	mise_harness_bin="$(mise which harness 2>/dev/null || true)"
	if [[ -n "$mise_harness_bin" && -x "$mise_harness_bin" ]]; then
		if run_check_environment_with_runner "mise harness ($mise_harness_bin)" "$mise_harness_bin"; then
			runner_ok=0
		else
			echo "Warning: mise-resolved harness failed; trying global npm fallback."
		fi
	fi
fi

if [[ "$runner_ok" -ne 0 ]]; then
	if command -v npm >/dev/null 2>&1; then
		if npm ls -g --depth=0 @brainwav/coding-harness >/dev/null 2>&1; then
			npm_global_bin=""
			npm_global_prefix="$(npm prefix -g 2>/dev/null || true)"
			if [[ -n "$npm_global_prefix" ]]; then
				npm_global_bin="$npm_global_prefix/bin"
			fi
			npm_harness_bin="$npm_global_bin/harness"
			if [[ -n "$npm_global_bin" && -x "$npm_harness_bin" ]]; then
				if run_check_environment_with_runner "global npm harness ($npm_harness_bin)" "$npm_harness_bin"; then
					runner_ok=0
				else
					echo "Warning: global npm harness failed to run check-environment."
				fi
			else
				echo "Warning: unable to resolve npm-global harness binary."
			fi
		else
			echo "Warning: @brainwav/coding-harness is not installed globally via npm."
		fi
	else
		echo "Warning: npm is not available for global harness fallback."
	fi
fi

if [[ "$runner_ok" -ne 0 ]]; then
	echo "Warning: no harness runner could execute check-environment successfully."
	echo "Warning: tried repo source CLI, repo dist CLI, repo dependency harness, repo wrapper, mise harness, global npm harness."
	echo "Warning: @brainwav/coding-harness is unavailable locally; full validation runs in CI with harness installed."
	jq -n \
		--arg checked_at "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
		'{
			passed: false,
			status: "blocked",
			skipped: true,
			check: "harness check-environment",
			reason: "@brainwav/coding-harness unavailable locally",
			checked_at: $checked_at
		}' > "$ATTESTATION_PATH"
fi

if ! jq -e '.passed == true' "$ATTESTATION_PATH" >/dev/null; then
	echo "Environment check blocked; harness validation did not pass (attestation: $ATTESTATION_PATH)" >&2
	exit 1
fi
echo "Environment check passed (attestation: $ATTESTATION_PATH)"
