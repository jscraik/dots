#!/usr/bin/env bash

set -euo pipefail
export PATH="$HOME/.local/share/mise/shims:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

input_json="$(cat)"
dots_hook_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
python3 "$dots_hook_dir/../scripts/admit-hook-fixture.py" "$input_json" || exit $?
parsed_fields="$(printf '%s' "$input_json" | jq -r '
  def command:
    (if (.tool_input? | type) == "object" then .tool_input.command else null end)
    // .command // "";
  def cwd:
    ((if (.tool_input? | type) == "object" then .tool_input.cwd else null end) | select(. != ""))
    // ((if (.tool_input? | type) == "object" then .tool_input.workdir else null end) | select(. != ""))
    // (.cwd | select(. != "")) // "";
  [(.tool_name // ""), (command | @base64), (cwd)] | join("\u001f")
')"
IFS=$'\x1f' read -r tool_name raw_command command_cwd <<<"$parsed_fields"

if [[ "$tool_name" != "Bash" ]]; then
  jq -n '{}'
  exit 0
fi

hook_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
if ! target_fields="$(python3 -I -S - "$raw_command" "$hook_dir/../scripts" <<'PY'
import base64
import shlex
import sys
import re
import runpy
policy = runpy.run_path(sys.argv[2] + "/pr-reconciliation.py")
reconciliation_thread = policy["reconciliation_thread"]
substitution_commands = policy["substitution_commands"]
protect_quoted_punctuation = policy["protect_quoted_punctuation"]
decode_protected_punctuation = policy["decode_protected_punctuation"]

def reject_unsupported():
    print("unsupported_command")
    raise SystemExit(0)

def shell_tokens(command):
    substitutions = substitution_commands(command)
    if substitutions is None or substitutions:
        reject_unsupported()
    lexer = shlex.shlex(protect_quoted_punctuation(command), posix=True, punctuation_chars=";&|<>()\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)

def reject_compound(tokens):
    if any(token and all(char in ";&|<>()\n" for char in token) for token in tokens):
        reject_unsupported()

try:
    tokens = shell_tokens(base64.b64decode(sys.argv[1]).decode())
except ValueError:
    reject_unsupported()

reject_compound(tokens)
assignment = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*")
for _ in range(4):
    while tokens and assignment.fullmatch(tokens[0]):
        tokens.pop(0)
    if not tokens or tokens[0].rsplit("/", 1)[-1] not in {"env", "sudo"}:
        break
    prefix = tokens.pop(0).rsplit("/", 1)[-1]
    value_options = {"env": {"-u", "--unset", "-C", "--chdir"}, "sudo": {"-u", "--user", "-g", "--group", "-h", "--host", "-p", "--prompt", "-C", "--close-from", "-R", "--chroot", "-D", "--chdir"}}[prefix]
    while tokens and tokens[0].startswith("-"):
        option = tokens.pop(0)
        if (option.startswith(("--chdir", "--chroot"))
            or re.fullmatch(r"-[^-]*" + ("C" if prefix == "env" else "[DR]") + r".*", option)):
            reject_unsupported()
        if option == "--":
            break
        if option in value_options and tokens:
            tokens.pop(0)
for _ in range(4):
    if not tokens or tokens[0].rsplit("/", 1)[-1] not in {"bash", "zsh", "sh"}:
        break
    command_index = next(
        (
            index + 1
            for index, token in enumerate(tokens[1:], start=1)
            if token.startswith("-") and not token.startswith("--") and "c" in token[1:] and index + 1 < len(tokens)
        ),
        None,
    )
    if command_index is None:
        break
    if command_index + 1 != len(tokens):
        reject_unsupported()
    try:
        tokens = shell_tokens(decode_protected_punctuation(tokens[command_index]))
    except ValueError:
        reject_unsupported()
    reject_compound(tokens)

tokens = [decode_protected_punctuation(token) for token in tokens]
try:
    index = next(
        index + 1
        for index, token in enumerate(tokens)
        if token.rsplit("/", 1)[-1] == "gh"
    )
except StopIteration:
    raise SystemExit(0)

if index != 1 or sum(token.rsplit("/", 1)[-1] == "gh" for token in tokens) != 1:
    reject_unsupported()

repo = ""
while index < len(tokens):
    token = tokens[index]
    if token in {"--repo", "-R", "--hostname"}:
        if index + 1 >= len(tokens):
            raise SystemExit(0)
        if token in {"--repo", "-R"}:
            repo = tokens[index + 1]
        index += 2
        continue
    if token.startswith("--repo="):
        repo = token.split("=", 1)[1]
        index += 1
        continue
    if token.startswith("-"):
        index += 1
        continue
    break

action = ""
pr_number = ""
thread_id = ""
base_ref = ""
head_ref = ""
if index + 1 < len(tokens) and tokens[index] == "pr":
    subcommand = tokens[index + 1]
    if subcommand == "create":
        action = "create"
        target_tokens = tokens[index + 2 :]
        for option_index, option in enumerate(target_tokens):
            if option in {"--repo", "-R"} and option_index + 1 < len(target_tokens):
                trailing_repo = target_tokens[option_index + 1]
                if repo and repo.casefold() != trailing_repo.casefold():
                    action = "target_conflict"
                else:
                    repo = trailing_repo
            elif option.startswith("--repo="):
                trailing_repo = option.split("=", 1)[1]
                if repo and repo.casefold() != trailing_repo.casefold():
                    action = "target_conflict"
                else:
                    repo = trailing_repo
            elif option in {"--base", "-B"} and option_index + 1 < len(target_tokens):
                base_ref = target_tokens[option_index + 1]
            elif option.startswith("--base="):
                base_ref = option.split("=", 1)[1]
            elif option.startswith("-B") and len(option) > 2:
                base_ref = option[2:]
            elif option in {"--head", "-H"} and option_index + 1 < len(target_tokens):
                head_ref = target_tokens[option_index + 1]
            elif option.startswith("--head="):
                head_ref = option.split("=", 1)[1]
            elif option.startswith("-H") and len(option) > 2:
                head_ref = option[2:]
    elif subcommand in {"edit", "merge", "review"}:
        action = "update"
        target_tokens = tokens[index + 2 :]
        trailing_repo = ""
        for option_index, option in enumerate(target_tokens):
            if option in {"--repo", "-R"} and option_index + 1 < len(target_tokens):
                trailing_repo = target_tokens[option_index + 1]
            elif option.startswith("--repo="):
                trailing_repo = option.split("=", 1)[1]
        if trailing_repo:
            if repo and repo.casefold() != trailing_repo.casefold():
                action = "target_conflict"
            else:
                repo = trailing_repo
        if target_tokens and not target_tokens[0].startswith("-"):
            target = target_tokens[0]
            if target.isdecimal():
                pr_number = target
            else:
                match = re.fullmatch(
                    r"https://github\.com/([^/]+/[^/]+)/pull/([0-9]+)/?", target
                )
                if match:
                    url_repo, pr_number = match.groups()
                    if repo and repo.casefold() != url_repo.casefold():
                        action = "target_conflict"
                    else:
                        repo = url_repo
elif index < len(tokens) and tokens[index] == "api":
    fields = {}
    api_tokens = tokens[index + 1 :]
    file_backed = any(option == "--input" or option.startswith("--input=") for option in api_tokens)
    option_index = 0
    while option_index < len(api_tokens):
        option = api_tokens[option_index]
        if option in {"-f", "--raw-field", "-F", "--field"}:
            if option_index + 1 >= len(api_tokens):
                break
            field = api_tokens[option_index + 1]
            option_index += 2
        elif option.startswith("--raw-field=") or option.startswith("--field="):
            field = option.split("=", 1)[1]
            option_index += 1
        elif option.startswith(("-f", "-F")) and len(option) > 2:
            field = option[2:]
            option_index += 1
        else:
            option_index += 1
            continue
        if "=" in field:
            name, value = field.split("=", 1)
            fields[name] = value
            if value.startswith("@") and (option in {"-F", "--field"} or option.startswith(("-F", "--field="))):
                file_backed = True
    query = fields.get("query", "")
    if "resolveReviewThread" in query or "addPullRequestReviewThreadReply" in query:
        action = "review_reconciliation"
        thread_id = reconciliation_thread(tokens)
    if "graphql" in api_tokens and file_backed:
        action = "unsupported_command"


print("\x1f".join((action, repo, pr_number, thread_id, base_ref, head_ref)))
PY
)"; then
  jq -n --arg reason "PR readiness is blocked because reconciliation policy analysis failed." '
    {hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$reason}}
  '
  exit 0
fi
IFS=$'\x1f' read -r readiness_phase expected_repo expected_pr expected_thread_id expected_base expected_head <<<"$target_fields"

if [[ -z "$readiness_phase" ]]; then
  jq -n '{}'
  exit 0
fi

if [[ "$readiness_phase" == "unsupported_command" ]]; then
  jq -n --arg reason "PR readiness requires one direct protected command per request; compound or uninspectable commands are denied." '
    {hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$reason}}
  '
  exit 0
fi

if [[ "$readiness_phase" == "target_conflict" ]]; then
  jq -n --arg reason "PR mutation is blocked because --repo and the pull-request URL name different repositories." '
    {hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$reason}}
  '
  exit 0
fi

if [[ "$readiness_phase" == "update" && -z "$expected_pr" ]]; then
  jq -n --arg reason "PR mutation is blocked because it does not name an explicit positional PR number or GitHub pull-request URL." '
    {hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$reason}}
  '
  exit 0
fi

if [[ "$readiness_phase" == "review_reconciliation" && -z "$expected_thread_id" ]]; then
  jq -n --arg reason "PR review reconciliation is blocked because the command does not expose an explicit threadId target." '
    {hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$reason}}
  '
  exit 0
fi

repo_root="${command_cwd:-$PWD}"
readiness_script="$HOME/.codex/scripts/pr-readiness.py"
if [[ ! -f "$readiness_script" ]]; then
  jq -n --arg reason "PR ${readiness_phase} is blocked because the projected pr-readiness gate is missing at ~/.codex/scripts/pr-readiness.py." '
    {hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$reason}}
  '
  exit 0
fi

readiness_args=(--phase "$readiness_phase" --repo-root "$repo_root" --check-receipt --json)
[[ -n "$expected_repo" ]] && readiness_args+=(--expected-repo "$expected_repo")
[[ -n "$expected_base" ]] && readiness_args+=(--expected-base "$expected_base")
[[ -n "$expected_head" ]] && readiness_args+=(--expected-head "$expected_head")
[[ -n "$expected_pr" ]] && readiness_args+=(--expected-pr "$expected_pr")
[[ -n "$expected_thread_id" ]] && readiness_args+=(--expected-thread-id "$expected_thread_id")

set +e
receipt_output="$(python3 "$readiness_script" "${readiness_args[@]}" 2>&1)"
receipt_code=$?
set -e
if [[ "$receipt_code" -eq 0 ]]; then
  jq -n --arg phase "$readiness_phase" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:("PR " + $phase + " readiness receipt is current and passing.")}}'
  exit 0
fi

reason="PR ${readiness_phase} is blocked until the ${readiness_phase}-phase readiness receipt passes. Run: python3 ~/.codex/scripts/pr-readiness.py --phase ${readiness_phase} --scope-file <repo-relative-scope-file> --write-receipt. Gate output: $(printf '%s' "$receipt_output" | jq -r '.error // .status // "blocked"' 2>/dev/null || printf '%s' "blocked")"
jq -n --arg reason "$reason" --arg phase "$readiness_phase" '
  {systemMessage:("PreToolUse blocked raw PR " + $phase + " because the readiness receipt is absent or stale."),hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$reason,arbitrationCandidate:{gate_id:"pr-readiness",owner_layer:"global_codex",source_path:"~/.codex/hooks/pr-readiness-guard.sh",decision:"block",reason:$reason,is_canonical_owner:true}}}
'
