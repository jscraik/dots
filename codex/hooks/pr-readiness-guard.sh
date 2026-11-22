#!/bin/bash -p

set -euo pipefail
# shellcheck source=codex/hooks/hook-runtime-path.sh
. "${BASH_SOURCE[0]%/*}/hook-runtime-path.sh" || exit 2

input_json="$(cat)"
dots_hook_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
python3 -I -S -B "$dots_hook_dir/../scripts/admit-hook-fixture.py" "$input_json" || exit $?
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
import os
import shlex
import sys
import re
import runpy
from urllib.parse import unquote, urlsplit
policy = runpy.run_path(sys.argv[2] + "/pr-reconciliation.py")
reconciliation_thread = policy["reconciliation_thread"]
substitution_commands = policy["substitution_commands"]
protect_quoted_punctuation = policy["protect_quoted_punctuation"]
decode_protected_punctuation = policy["decode_protected_punctuation"]
pr_command_phase = policy["pr_command_phase"]

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
target_override = False
target_environment = {"GH_HOST", "GH_REPO"}
effective_targets = {name for name in target_environment if os.environ.get(name)}
wrapped_command = False
for _ in range(4):
    while tokens and assignment.fullmatch(tokens[0]):
        if tokens[0].partition("=")[0] in target_environment:
            effective_targets.add(tokens[0].partition("=")[0])
        tokens.pop(0)
    if not tokens or tokens[0].rsplit("/", 1)[-1] not in {"env", "sudo"}:
        break
    prefix = tokens.pop(0).rsplit("/", 1)[-1]
    wrapped_command = True
    value_options = {"env": {"-u", "--unset", "-C", "--chdir"}, "sudo": {"-u", "--user", "-g", "--group", "-h", "--host", "-p", "--prompt", "-C", "--close-from", "-R", "--chroot", "-D", "--chdir"}}[prefix]
    while tokens and tokens[0].startswith("-"):
        option = tokens.pop(0)
        if (option.startswith(("--chdir", "--chroot"))
            or re.fullmatch(r"-[^-]*" + ("C" if prefix == "env" else "[DR]") + r".*", option)):
            reject_unsupported()
        if prefix == "env":
            if option in {"-i", "--ignore-environment", "-"}:
                effective_targets.clear()
                continue
            if option in {"-u", "--unset"}:
                if not tokens: reject_unsupported()
                effective_targets.discard(tokens.pop(0))
                continue
            if option.startswith("--unset="):
                effective_targets.discard(option.partition("=")[2])
                continue
            if option.startswith("-u"):
                effective_targets.discard(option[2:])
                continue
        if option == "--":
            break
        if option in value_options and tokens:
            if prefix == "env" and option in {"-u", "--unset"} and tokens[0] in {"GH_HOST", "GH_REPO"}:
                target_override = True
            tokens.pop(0)
        elif prefix == "env" and option.startswith("--unset=") and option.split("=", 1)[1] in {"GH_HOST", "GH_REPO"}:
            target_override = True
target_environment_override = bool(effective_targets)
target_override = target_environment_override
for _ in range(4):
    if not tokens or tokens[0].rsplit("/", 1)[-1] not in {"bash", "zsh", "sh"}:
        break
    wrapped_command = True
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
hostname = ""
while index < len(tokens):
    token = tokens[index]
    if token in {"--repo", "-R", "--hostname"}:
        if index + 1 >= len(tokens):
            raise SystemExit(0)
        if token in {"--repo", "-R"}:
            repo = tokens[index + 1]
        else:
            hostname = tokens[index + 1]
        index += 2
        continue
    if token.startswith("--repo="):
        repo = token.split("=", 1)[1]
        index += 1
        continue
    if token.startswith("-R") and len(token) > 2:
        repo = token[2:]
        index += 1
        continue
    if token.startswith("--hostname="):
        hostname = token.split("=", 1)[1]
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
if index < len(tokens) and tokens[index] == "pr":
    if index + 1 >= len(tokens):
        action = "unsupported_command"
    else:
        subcommand = tokens[index + 1]
        action = pr_command_phase(subcommand)
    if action == "create":
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
            elif option.startswith("-R") and len(option) > 2:
                trailing_repo = option[2:]
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
    elif action == "update":
        action = "update"
        target_tokens = tokens[index + 2 :]
        trailing_repo = ""
        for option_index, option in enumerate(target_tokens):
            if option in {"--repo", "-R"} and option_index + 1 < len(target_tokens):
                trailing_repo = target_tokens[option_index + 1]
            elif option.startswith("--repo="):
                trailing_repo = option.split("=", 1)[1]
            elif option.startswith("-R") and len(option) > 2:
                trailing_repo = option[2:]
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
    endpoint = ""
    explicit_method = ""
    body_supplied = False
    file_backed = False
    ambiguous_api = False
    value_options = {
        "--cache", "-H", "--header", "--hostname", "--jq", "-q",
        "-p", "--preview", "-t", "--template",
    }
    flag_options = {
        "-h", "--help", "-i", "--include", "--paginate", "--silent", "--slurp", "--verbose",
    }

    def unsafe_api_header(value):
        name, separator, _header_value = value.partition(":")
        return bool(separator) and name.strip().casefold() in {"host", "x-http-method-override"}

    option_index = 0
    while option_index < len(api_tokens):
        option = api_tokens[option_index]
        field = None
        if option in {"-X", "--method"}:
            if option_index + 1 >= len(api_tokens) or explicit_method:
                ambiguous_api = True
                option_index += 1
                continue
            explicit_method = api_tokens[option_index + 1]
            option_index += 2
            continue
        if option.startswith("--method=") or option.startswith("-X") and len(option) > 2:
            if explicit_method:
                ambiguous_api = True
            explicit_method = option.split("=", 1)[1] if option.startswith("--method=") else option[2:].removeprefix("=")
            option_index += 1
            continue
        if option in {"-f", "--raw-field", "-F", "--field"}:
            if option_index + 1 >= len(api_tokens):
                ambiguous_api = True
                option_index += 1
                continue
            field = api_tokens[option_index + 1]
            body_supplied = True
            option_index += 2
        elif option.startswith("--raw-field=") or option.startswith("--field="):
            field = option.split("=", 1)[1]
            body_supplied = True
            option_index += 1
        elif option.startswith(("-f", "-F")) and len(option) > 2:
            field = option[2:]
            body_supplied = True
            option_index += 1
        elif option == "--input":
            if option_index + 1 >= len(api_tokens):
                ambiguous_api = True
                option_index += 1
                continue
            body_supplied = True
            file_backed = True
            option_index += 2
            continue
        elif option.startswith("--input="):
            body_supplied = True
            file_backed = True
            option_index += 1
            continue
        elif option in value_options:
            if option_index + 1 >= len(api_tokens):
                ambiguous_api = True
                option_index += 1
                continue
            if option == "--hostname":
                hostname = api_tokens[option_index + 1]
            if option in {"-H", "--header"} and unsafe_api_header(api_tokens[option_index + 1]):
                ambiguous_api = True
            option_index += 2
            continue
        elif option.startswith("--hostname="):
            hostname = option.split("=", 1)[1]
            option_index += 1
            continue
        elif option.startswith("--header=") or option.startswith("-H") and len(option) > 2:
            header = option.split("=", 1)[1] if option.startswith("--header=") else option[2:]
            ambiguous_api |= unsafe_api_header(header)
            option_index += 1
            continue
        elif any(option.startswith(prefix) for prefix in (
            "--cache=", "--jq=", "--preview=", "--template=",
        )) or any(option.startswith(prefix) and len(option) > 2 for prefix in ("-q", "-p", "-t")) or option in flag_options:
            option_index += 1
            continue
        elif option.startswith("-"):
            ambiguous_api = True
            option_index += 1
            continue
        else:
            if endpoint:
                ambiguous_api = True
            else:
                endpoint = option
            option_index += 1
            continue
        if field is not None and "=" in field:
            name, value = field.split("=", 1)
            if name in fields and not name.endswith("[]"):
                ambiguous_api = True
            fields[name] = value
            if value.startswith("@") and (option in {"-F", "--field"} or option.startswith(("-F", "--field="))):
                file_backed = True
        elif field is not None and not field.endswith("[]"):
            ambiguous_api = True
    method = explicit_method.upper() if explicit_method else "POST" if body_supplied else "GET"
    if not re.fullmatch(r"[A-Z]+", method):
        ambiguous_api = True
    query = fields.get("query", "")
    if endpoint.casefold() == "graphql":
        # Ignore GraphQL comments and string values when classifying operations.
        query_code = re.sub(r'"""(?:[^"\\]|\\.|"(?!""))*"""|"(?:[^"\\]|\\.)*"|#[^\r\n]*', ' ', query)
        if "resolveReviewThread" in query_code or "addPullRequestReviewThreadReply" in query_code:
            action = "review_reconciliation"
            thread_id = reconciliation_thread(tokens)
        if (file_backed or ambiguous_api or action and (target_override or wrapped_command or hostname)
            or re.search(r"\bmutation\b", query_code) and not action):
            action = "unsupported_command"
    else:
        normalized_endpoint = endpoint
        absolute_endpoint = "://" in normalized_endpoint
        if absolute_endpoint:
            parsed_endpoint = urlsplit(normalized_endpoint)
            if parsed_endpoint.scheme.casefold() not in {"http", "https"} or not parsed_endpoint.netloc:
                ambiguous_api = True
            normalized_endpoint = parsed_endpoint.path
        else:
            normalized_endpoint = "/" + normalized_endpoint.lstrip("/")
        for _ in range(3):
            decoded_endpoint = unquote(normalized_endpoint)
            if decoded_endpoint == normalized_endpoint:
                break
            normalized_endpoint = decoded_endpoint
        merge_match = re.fullmatch(
            r"(?:/api/v3)?/repos/([^/]+)/([^/]+)/pulls/([1-9][0-9]*)/merge/?",
            normalized_endpoint,
            re.IGNORECASE,
        )
        if ambiguous_api:
            action = "unsupported_command"
        elif method not in {"GET", "HEAD"} and (target_override or wrapped_command or hostname or absolute_endpoint):
            action = "unsupported_command"
        elif method == "PUT" and merge_match:
            owner, name, pr_number = merge_match.groups()
            if "{" not in owner + name and "}" not in owner + name:
                action = "update"
                endpoint_repo = f"{owner}/{name}"
                if repo and repo.casefold() != endpoint_repo.casefold():
                    action = "target_conflict"
                else:
                    repo = endpoint_repo
            else:
                action = "unsupported_command"
        elif method not in {"GET", "HEAD"}:
            action = "unsupported_command"

if (target_environment_override or hostname) and action in {"create", "update", "review_reconciliation"}:
    action = "target_environment_override"

print("\x1f".join((action, repo, pr_number, thread_id, base_ref, head_ref)))
PY
)"; then
  jq -n --arg reason "PR readiness is blocked because reconciliation policy analysis failed." '
    {hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$reason}}
  '
  exit 0
fi
IFS=$'\x1f' read -r readiness_phase expected_repo expected_pr expected_thread_id expected_base expected_head <<<"$target_fields"

if [[ -z "$readiness_phase" || "$readiness_phase" == "read_only" ]]; then
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
  jq -n --arg reason "PR mutation is blocked because --repo and the pull-request target name different repositories." '
    {hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$reason}}
  '
  exit 0
fi

if [[ "$readiness_phase" == "target_environment_override" ]]; then
  jq -n --arg reason "Protected PR command is blocked because GH_REPO or GH_HOST, or --hostname, would override the repository or host bound to readiness evidence." '
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
