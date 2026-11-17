#!/usr/bin/env bash

set -euo pipefail
export PATH="$HOME/.local/share/mise/shims:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

input_json="$(cat)"
dots_hook_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
python3 "$dots_hook_dir/../scripts/admit-hook-fixture.py" "$input_json" || exit $?
hook_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
codex_repo_root="$(cd -P "$hook_dir/.." && pwd -P)"
runtime_policy_script="$codex_repo_root/scripts/hook-governance/hook_runtime_policy.py"
timeout_class="pre_safety_fail_closed"

if [[ -f "$runtime_policy_script" ]]; then
  timeout_class="$(
    python3 "$runtime_policy_script" --event PreToolUse --field timeout_class 2>/dev/null \
      || printf '%s' "$timeout_class"
  )"
fi

parsed_fields="$(printf '%s' "$input_json" | jq -r '
  def tool_command:
    (if (.tool_input? | type) == "object" then .tool_input.command else null end)
    // .command
    // "";
  def tool_cwd:
    ((if (.tool_input? | type) == "object" then .tool_input.cwd else null end) | select(. != ""))
    // ((if (.tool_input? | type) == "object" then .tool_input.workdir else null end) | select(. != ""))
    // (.cwd | select(. != ""))
    // "";
  [.tool_name // "", tool_command, tool_cwd, .permission_mode // "default"] | @tsv
')"
IFS=$'\t' read -r tool_name raw_command cwd permission_mode <<<"$parsed_fields"

# run_ok outputs a JSON object signalling the PreToolUse hook permits the tool invocation to proceed.
run_ok() {
  jq -n '{}'
}

# run_block emits a JSON denial for the PreToolUse gate to stdout using the provided reason and the current permission mode and timeout class.
run_block() {
  local reason="$1"
  jq -n \
    --arg reason "$reason" \
    --arg mode "$permission_mode" \
    --arg timeout_class "$timeout_class" \
    '{
      systemMessage: ("PreToolUse blocked commit-time validation in permission mode " + $mode + "."),
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: $reason,
        arbitrationCandidate: {
          gate_id: "commit-validation",
          owner_layer: "project_codex",
          source_path: "~/.codex/hooks/pre-commit-tests.sh",
          decision: "block",
          reason: $reason,
          is_canonical_owner: false,
          timeout_class: $timeout_class
        }
      }
    }'
}

if [[ "$tool_name" != "Bash" ]]; then
  run_ok
  exit 0
fi

# Resolve only a literal, single Git commit. Never execute the supplied command.
# Directory overrides are interpreted in order, then Git supplies the worktree
# root so invocation from a nested directory identifies the owning project.
if ! run_dir="$(python3 -I -S - "$input_json" "$codex_repo_root/scripts/pr-reconciliation.py" <<'PY'
import json
import os
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

try:
    payload = json.loads(sys.argv[1])
    tool = payload.get("tool_input")
    tool = tool if isinstance(tool, dict) else {}
    command = tool.get("command") or payload.get("command") or ""
    active_cwd = payload.get("cwd")
    cwd = tool.get("cwd") or tool.get("workdir") or active_cwd
    if (not isinstance(command, str) or not isinstance(cwd, str)
            or not isinstance(active_cwd, str) or not Path(active_cwd).is_absolute()):
        raise ValueError("invalid command or working directory")
    policy = runpy.run_path(sys.argv[2])
    if policy["substitution_commands"](command) != []:
        raise ValueError("command substitutions are not supported")
    # shlex does not perform shell expansion. Only admit literal words, so
    # an attached message cannot expand into options that bypass safeguards.
    # Single quotes and backslash escapes keep expansion characters as data;
    # double quotes still permit parameter/arithmetic/command expansion.
    quote = None
    index = 0
    while index < len(command):
        char = command[index]
        if quote == "'":
            if char == "'":
                quote = None
        elif char == "\\":
            index += 1
        elif char == "'" and quote is None:
            quote = char
        elif char == '"':
            quote = None if quote == char else char
        elif char in ("$", chr(96)) or (quote is None and char in "*?[]{}~"):
            raise ValueError("shell expansions are not supported; quote literal arguments")
        index += 1
    protected = policy["protect_quoted_punctuation"](command)
    lexer = shlex.shlex(protected, posix=True, punctuation_chars=";&|<>()\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    tokens = list(lexer)
    if any(token and all(c in ";&|<>()\n" for c in token) for token in tokens):
        raise ValueError("use one direct commit command per request")
    tokens = [policy["decode_protected_punctuation"](token) for token in tokens]
    while tokens and (re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[0])
                      or tokens[0] in {"command", "env"}):
        token = tokens.pop(0)
        if token.startswith("GIT_") or token.startswith(("HOME=", "PATH=", "MISE_")):
            raise ValueError("execution environment overrides are not supported")
    if not tokens or tokens.pop(0) not in {"git", "/usr/bin/git", "/opt/homebrew/bin/git"}:
        raise ValueError("use a direct git commit command")
    if any(os.environ.get(key) for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES")):
        raise ValueError("Git repository environment overrides are not supported")
    def reject_symlink_components(path):
        current = Path(path.anchor)
        for part in path.parts[1:]:
            current = current / part
            if current.is_symlink():
                raise ValueError("symlink commit targets are not supported")

    target = Path(active_cwd) / cwd
    reject_symlink_components(target)
    while tokens and tokens[0] != "commit":
        option = tokens.pop(0)
        if option == "-C" or option.startswith("-C"):
            if option == "-C":
                if not tokens:
                    raise ValueError("missing -C directory")
                directory = tokens.pop(0)
            else:
                directory = option[2:]
            if any(c in directory for c in (chr(96) + "$*?[]{}~\n\r\t")):
                raise ValueError("-C requires a literal directory")
            if directory:
                target = target / directory
                reject_symlink_components(target)
        elif option not in {"--no-pager", "--literal-pathspecs", "--no-optional-locks"}:
            raise ValueError("unsupported Git global option: " + option)
    if not tokens:
        raise ValueError("git commit target was not found")
    options = tokens[1:]
    value_options = {"-m", "--message", "-F", "--file", "--cleanup", "--trailer"}
    switches = {"--allow-empty", "--allow-empty-message", "--signoff", "-s", "--verbose", "-v", "--quiet", "-q", "-S", "--gpg-sign"}
    while options:
        option = options.pop(0)
        if option in value_options:
            if not options:
                raise ValueError("missing commit option value")
            options.pop(0)
        elif option in switches:
            continue
        elif any(option.startswith(prefix + "=") for prefix in value_options if prefix.startswith("--")):
            continue
        elif option.startswith("-m") and len(option) > 2:
            continue
        else:
            raise ValueError("unsupported commit option")
    result = subprocess.run(["git", "-C", str(target), "rev-parse", "--show-toplevel"],
                            text=True, capture_output=True, timeout=5, check=True)
    resolved = result.stdout.rstrip("\n")
    if not resolved or any(c in resolved for c in "\n\r\t") or not Path(resolved).is_dir():
        raise ValueError("invalid Git worktree root")
    # The event cwd identifies the active worktree. Command arguments and tool
    # directory overrides are not authority to execute another checkout's code
    # during PreToolUse, before the command's permission decision.
    active = subprocess.run(["git", "-C", active_cwd, "rev-parse", "--show-toplevel"],
                            text=True, capture_output=True, timeout=5, check=True)
    active_root = active.stdout.rstrip("\n")
    if (not active_root or any(c in active_root for c in "\n\r\t")
            or Path(resolved).resolve(strict=True) != Path(active_root).resolve(strict=True)):
        raise ValueError("commit validation must stay in the active worktree")
    expected = {"commit.gpgsign": "true", "gpg.format": "ssh",
                "gpg.ssh.program": "/Applications/1Password.app/Contents/MacOS/op-ssh-sign"}
    for key, value in expected.items():
        actual = subprocess.run(["git", "-C", resolved, "config", "--get", key],
                                capture_output=True, text=True, timeout=5, check=False)
        if actual.returncode != 0 or actual.stdout.rstrip("\n") != value:
            raise ValueError("effective Git signing configuration must use 1Password: " + key)
    print(resolved)
except (ValueError, OSError, subprocess.SubprocessError) as error:
    print("Cannot resolve commit validation target: " + str(error), file=sys.stderr)
    raise SystemExit(1)
PY
)"; then
  run_block "Cannot resolve commit validation target. Use one direct git commit within the active worktree with literal -C directories; cross-worktree, repository and execution-environment overrides are not supported."
  exit 0
fi

# Metadata inspection is passive; repository-owned validation must not run before
# the tool permission decision, including inside the active worktree.
if [[ -f "$run_dir/package.json" ]] && ! jq -e 'type == "object" and ((.scripts? // {}) | type == "object")' "$run_dir/package.json" >/dev/null 2>&1; then
  run_block "package.json is malformed or .scripts is not an object."
  exit 0
fi

# Structural admission is not execution approval. Leave the tool's native
# sandbox and approval policy to decide whether this command may execute.
# Git runs its normal hooks and configured 1Password signer after that decision.
jq -n '{hookSpecificOutput: {hookEventName: "PreToolUse", additionalContext: "Commit syntax and active-worktree scope passed. Native execution approval still applies; Git hooks and configured signing remain required."}}'
