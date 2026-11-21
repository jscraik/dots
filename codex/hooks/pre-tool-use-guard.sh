#!/bin/bash -p
set -euo pipefail
# shellcheck source=codex/hooks/hook-runtime-path.sh
. "${BASH_SOURCE[0]%/*}/hook-runtime-path.sh" || exit 2
input_json="$(cat)"
dots_hook_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
python3 -I -S -B "$dots_hook_dir/../scripts/admit-hook-fixture.py" "$input_json" || exit $?
hook_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
codex_repo_root="$(cd -P "$hook_dir/.." && pwd -P)"
# shellcheck source=codex/hooks/hook-runtime-lib.sh
. "$hook_dir/hook-runtime-lib.sh" || exit 2
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
    ([if (.tool_input? | type) == "object" then .tool_input.cwd, .tool_input.workdir else null end, .cwd]
    | map(select(. != null and . != "")) | if length > 0 then .[0] else "" end)
    | if type != "string" then "__codex_invalid_cwd__"
      elif test("[\\x00-\\x1f\\x7f]") then "__codex_invalid_cwd__" else . end;
  def edit_payload:
    (if (.tool_input? | type) == "object" then
      [
        .tool_input.path,
        .tool_input.file_path,
        .tool_input.filePath,
        .tool_input.target_file,
        .tool_input.target,
        .tool_input.filename
      ]
    else [] end)
    + (if ((.tool_input? | type) == "object") and ((.tool_input.patch? | type) == "string") then
        (.tool_input.patch
        | split("\n")
        | map(select(test("^\\*\\*\\* (Add|Update|Delete) File: |^\\*\\*\\* Move to: ")))
        | map(
            sub("^\\*\\*\\* (Add|Update|Delete) File: "; "")
            | sub("^\\*\\*\\* Move to: "; "")
          ))
      else [] end)
    + (if (tool_command | type) == "string" and (tool_command | length) > 0 then
        (tool_command
        | split("\n")
        | map(select(test("^\\*\\*\\* (Add|Update|Delete) File: |^\\*\\*\\* Move to: ")))
        | map(
            sub("^\\*\\*\\* (Add|Update|Delete) File: "; "")
            | sub("^\\*\\*\\* Move to: "; "")
          ))
      else [] end)
    | map(select(. != null) | tostring)
    | join("\u001e");
  [.tool_name // "", (tool_command | @base64), tool_cwd, .permission_mode // "default", .session_id // "", .turn_id // "", edit_payload] | join("\u001f")
')"
IFS=$'\x1f' read -r tool_name encoded_command _command_cwd permission_mode session_id turn_id edit_targets <<<"$parsed_fields"
raw_command="$(printf '%s' "$encoded_command" | jq -Rr '@base64d')"
git_worktree_risk=""
run_ok() {
  jq -n '{}'
}
run_block() {
  local reason="$1"
  local event_record
  event_record="$(hook_runtime_event_envelope "$input_json" "pre-tool-use" "pre-tool-use-guard" "deny" "$reason")"
  if [[ -n "$event_record" ]]; then
    hook_runtime_append_jsonl "$(hook_runtime_log_path "hook-events")" "$event_record" "pre-tool-use-guard" || true
  fi
  jq -n \
    --arg reason "$reason" \
    --arg mode "$permission_mode" \
    --arg timeout_class "$timeout_class" \
    '{
      systemMessage: ("PreToolUse blocked a denied tool action in permission mode " + $mode + "."),
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: $reason,
        arbitrationCandidate: {
          gate_id: "command-safety",
          owner_layer: "global_codex",
          source_path: "~/.codex/hooks/pre-tool-use-guard.sh",
          decision: "block",
          reason: $reason,
          is_canonical_owner: false,
          timeout_class: $timeout_class
        }
      }
    }'
}
tokenize_command() {
  python3 -I -S - "$1" <<'PY'
import shlex
import sys
import re

SHELL_PUNCTUATION = ";&|(){}"
SHELL_SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "{", "}"}
QUOTED_SEPARATOR_PREFIX = "\x1e"
ESCAPED_SEPARATOR_MARKERS = {
    character: chr(0xE000 + index)
    for index, character in enumerate(SHELL_PUNCTUATION)
}
MARKER_SEPARATORS = {marker: character for character, marker in ESCAPED_SEPARATOR_MARKERS.items()}


def shell_split(command):
    protected = []
    quote = None
    index = 0
    while index < len(command):
        character = command[index]
        if quote is not None:
            protected.append(character)
            if character == quote:
                quote = None
            elif character == "\\" and quote == '"' and index + 1 < len(command):
                index += 1
                protected.append(command[index])
            index += 1
            continue
        if character in {"'", '"'}:
            quote = character
            protected.append(character)
            index += 1
            continue
        if character == "\\" and index + 1 < len(command):
            escaped = command[index + 1]
            if escaped in ESCAPED_SEPARATOR_MARKERS:
                protected.append(ESCAPED_SEPARATOR_MARKERS[escaped])
                index += 2
                continue
            if escaped == "\n":
                index += 2
                continue
            protected.extend((character, escaped))
            index += 2
            continue
        if character == "\n":
            protected.extend((" ", ";", " "))
        else:
            protected.append(character)
        index += 1
    protected_command = "".join(protected)

    def lex(posix):
        lexer = shlex.shlex(protected_command, posix=posix, punctuation_chars=SHELL_PUNCTUATION)
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)

    tokens = lex(True)
    source_tokens = lex(False)
    for index, token in enumerate(tokens):
        if token in MARKER_SEPARATORS:
            tokens[index] = QUOTED_SEPARATOR_PREFIX + MARKER_SEPARATORS[token]
            continue
        for marker, separator in MARKER_SEPARATORS.items():
            tokens[index] = tokens[index].replace(marker, separator)
    if len(tokens) == len(source_tokens):
        for index, (token, source_token) in enumerate(zip(tokens, source_tokens)):
            if (
                token in SHELL_SEPARATORS
                and len(source_token) >= 2
                and source_token[0] == source_token[-1]
                and source_token[0] in {"'", '"'}
            ):
                tokens[index] = QUOTED_SEPARATOR_PREFIX + token
    return tokens


try:
    tokens = shell_split(sys.argv[1])
except ValueError:
    raise SystemExit(2)

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
        if option == "--":
            break
        if option in value_options and tokens:
            tokens.pop(0)
def shell_payload_index(items, start=0):
    for index in range(start + 1, len(items)):
        option = items[index]
        if not option.startswith("-") or option == "--" or option in SHELL_SEPARATORS:
            break
        if not option.startswith("--") and "c" in option[1:]:
            payload = index + 1
            if payload < len(items) and items[payload] == "--":
                payload += 1
            return payload if payload < len(items) and items[payload] not in SHELL_SEPARATORS else None
    return None


for _ in range(4):
    if not tokens or tokens[0].rsplit("/", 1)[-1] not in {"bash", "zsh", "sh"}:
        break
    command_index = shell_payload_index(tokens)
    if command_index is None:
        break
    try:
        tokens = shell_split(tokens[command_index])
    except ValueError:
        raise SystemExit(2)

shells = {"bash", "zsh", "sh"}


def expose_nested_shell_commands(items, depth=0):
    if depth >= 4:
        return items
    expanded = []
    index = 0
    while index < len(items):
        token = items[index]
        expanded.append(token)
        if token.rsplit("/", 1)[-1] not in shells:
            index += 1
            continue
        command_index = shell_payload_index(items, index)
        if command_index is None:
            index += 1
            continue
        try:
            nested = shell_split(items[command_index])
        except ValueError:
            raise SystemExit(2)
        expanded.append(";")
        expanded.extend(expose_nested_shell_commands(nested, depth + 1))
        index = command_index + 1
    return expanded


tokens = expose_nested_shell_commands(tokens)
print("\x1f".join(tokens))
PY
}
is_shell_separator_token() {
  case "$1" in
    ';'|'&&'|'||'|'|'|'&'|'('|')'|'{'|'}') return 0 ;;
  esac
  return 1
}
is_command_start_predecessor() {
  if is_shell_separator_token "$1"; then
    return 0
  fi
  case "$1" in
    if|while|until|then|do|else|elif|'!') return 0 ;;
  esac
  return 1
}
git_subcommand_index() {
  local command_text="$1"
  local wanted="$2"
  local start_index="${3:-0}"
  local -a tokens
  local encoded_tokens
  encoded_tokens="$(tokenize_command "$command_text")" || return 1
  IFS=$'\x1f' read -ra tokens <<< "$encoded_tokens"
  local idx="$start_index"
  for ((idx=start_index; idx<${#tokens[@]}; idx++)); do
    [[ "${tokens[idx]##*/}" == "git" ]] || continue
    local command_position=false
    if ((idx > 0)); then
      local previous_token="${tokens[idx-1]}"
      if is_command_start_predecessor "$previous_token"; then
        command_position=true
      else
        local segment_start=$((idx - 1))
        while ((segment_start > 0)); do
          local boundary_token="${tokens[segment_start-1]}"
          if is_command_start_predecessor "$boundary_token"; then
            break
          fi
          ((segment_start-=1))
        done
        local prefix_index=$segment_start
        while ((prefix_index < idx)) \
          && [[ "${tokens[prefix_index]}" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; do
          ((prefix_index+=1))
        done
        if ((prefix_index == idx)); then
          command_position=true
        else
          case "${tokens[prefix_index]##*/}" in
            env|sudo|command) command_position=true ;;
          esac
        fi
      fi
    else
      command_position=true
    fi
    if [[ "$command_position" != true ]]; then
      continue
    fi
    local scan_idx
    for ((scan_idx=idx+1; scan_idx<${#tokens[@]}; scan_idx++)); do
      case "${tokens[scan_idx]}" in
        -C|-c|--git-dir|--work-tree|--namespace|--config-env)
          ((scan_idx+=1))
          ;;
        --git-dir=*|--work-tree=*|--namespace=*|--config-env=*|-c=*|-*)
          ;;
        "$wanted")
          printf '%s\n' "$scan_idx"
          return 0
          ;;
        *)
          break
          ;;
      esac
    done
  done
  return 1
}
# Tokenize before matching gh subcommands so tabs/extra spaces still route.
_gh_scan_subcommand() {
  local command_text="$1"
  local wanted="$2"
  local -a tokens
  local encoded_tokens idx scan_idx
  encoded_tokens="$(tokenize_command "$command_text")" || return 1
  IFS=$'\x1f' read -ra tokens <<< "$encoded_tokens"
  for ((idx=0; idx<${#tokens[@]}; idx++)); do
    [[ "${tokens[idx]##*/}" == "gh" ]] || continue
    for ((scan_idx=idx+1; scan_idx<${#tokens[@]}; scan_idx++)); do
      case "${tokens[scan_idx]}" in
        --repo|-R|-r|--hostname) ((scan_idx+=1)) ;;
        --repo=*|--hostname=*|-*) ;;
        "$wanted")
          if [[ -z "${3:-}" ]]; then
            return 0
          fi
          if ((scan_idx + 1 < ${#tokens[@]})) && [[ "${tokens[scan_idx+1]}" == "$3" ]]; then
            printf '%s\n' "$((scan_idx + 1))"
            return 0
          fi
          break
          ;;
        *) break ;;
      esac
    done
  done
  return 1
}
gh_pr_subcommand_index() {
  _gh_scan_subcommand "$1" pr "$2"
}
gh_api_command() {
  _gh_scan_subcommand "$1" api
}
contains_git_commit_no_verify() {
  local command_text="$1"
  local -a tokens
  local encoded_tokens
  encoded_tokens="$(tokenize_command "$command_text")" || return 1
  IFS=$'\x1f' read -ra tokens <<< "$encoded_tokens"
  local search_index=0
  local idx
  while idx="$(git_subcommand_index "$command_text" commit "$search_index")"; do
    search_index=$((idx + 1))
    for ((idx=idx+1; idx<${#tokens[@]}; idx++)); do
      local token="${tokens[idx]}"
      is_shell_separator_token "$token" && break
      if [[ "$token" == "--no-verify" || "$token" == "-n" ]]; then
        return 0
      fi
    done
  done
  return 1
}
contains_git_push_no_verify() {
  local command_text="$1"
  local -a tokens
  local encoded_tokens
  encoded_tokens="$(tokenize_command "$command_text")" || return 1
  IFS=$'\x1f' read -ra tokens <<< "$encoded_tokens"
  local search_index=0
  local idx
  while idx="$(git_subcommand_index "$command_text" push "$search_index")"; do
    search_index=$((idx + 1))
    for ((idx=idx+1; idx<${#tokens[@]}; idx++)); do
      local token="${tokens[idx]}"
      is_shell_separator_token "$token" && break
      if [[ "$token" == "--no-verify" ]]; then
        return 0
      fi
    done
  done
  return 1
}
contains_protected_destination_push() {
  local command_text="$1"
  local -a tokens
  local encoded_tokens
  encoded_tokens="$(tokenize_command "$command_text")" || return 1
  IFS=$'\x1f' read -ra tokens <<< "$encoded_tokens"
  local search_index=0
  local push_idx
  while push_idx="$(git_subcommand_index "$command_text" push "$search_index")"; do
    search_index=$((push_idx + 1))
    local remote_seen=false
    local idx
    for ((idx=push_idx+1; idx<${#tokens[@]}; idx++)); do
      local token="${tokens[idx]}"
      is_shell_separator_token "$token" && break
      if [[ "$token" == -* || "$token" == *=* ]]; then
        continue
      fi
      if [[ "$remote_seen" != true ]]; then
        remote_seen=true
        continue
      fi
      # Normalize the destination side of a refspec. Git accepts both short
      # names (feature:main) and fully qualified refs (feature:refs/heads/main),
      # as well as an unqualified main/master ref with no colon.
      local destination="$token"
      if [[ "$token" == *:* ]]; then
        destination="${token##*:}"
      fi
      destination="${destination#refs/heads/}"
      if [[ "$destination" == "main" || "$destination" == "master" ]]; then
        return 0
      fi
    done
  done
  return 1
}
is_forbidden_push_long_option() {
  # Git accepts unambiguous long-option prefixes; deny every spelling of the
  # destructive/broad push flags (including --branches as --all's alias).
  local option="${1%%=*}"
  case "$option" in
    --pru|--prun|--prune) return 0 ;;
    --d|--de|--del|--dele|--delet|--delete) return 0 ;;
    --fo|--for|--forc|--force) return 0 ;;
    --force-with-lease|--force-with-leas|--force-with-lea|--force-with-le|--force-with-l|--force-with-|--force-with|--force-wit|--force-wi|--force-w) return 0 ;;
    --m|--mi|--mir|--mirr|--mirro|--mirror) return 0 ;;
    --al|--all) return 0 ;;
    --b|--br|--bra|--bran|--branc|--branch|--branche|--branches) return 0 ;;
    --ta|--tag|--tags) return 0 ;;
  esac
  return 1
}
contains_forbidden_push_option() {
  local command_text="$1"
  local -a tokens
  local encoded_tokens
  encoded_tokens="$(tokenize_command "$command_text")" || return 1
  IFS=$'\x1f' read -ra tokens <<< "$encoded_tokens"
  local search_index=0
  local push_idx
  while push_idx="$(git_subcommand_index "$command_text" push "$search_index")"; do
    search_index=$((push_idx + 1))
    local options=true
    local idx
    for ((idx=push_idx+1; idx<${#tokens[@]}; idx++)); do
      local token="${tokens[idx]}"
      is_shell_separator_token "$token" && break
      if [[ "$token" == "--" ]]; then options=false; continue; fi
      if [[ "$options" == true ]]; then
        if [[ "$token" =~ ^-[^-o]*o$ && "$token" != *[fd]* ]]; then idx=$((idx+1)); continue; fi
        case "$token" in
          -o|--repo|--recurse-submodules|--pu|--pus|--push|--push-|--push-o|--push-op|--push-opt|--push-opti|--push-optio|--push-option) idx=$((idx+1)); continue ;;
          -o?*|--repo=*|--recurse-submodules=*|--push*=*) continue ;;
        esac
        [[ "$token" == --* ]] && is_forbidden_push_long_option "$token" && return 0
      fi
      case "$token" in
        -f|-d|-[!-]*[fd]*|+*|:*) return 0 ;;
      esac
    done
  done
  return 1
}
branch_option_consumes_value() {
  case "$1" in
    -u|--format|--for|--form|--forma|--sort|--so|--sor)
      return 0
      ;;
    --contains|--contain|--contai|--conta|--cont)
      return 0
      ;;
    --merged|--merge|--merg|--no-merged|--no-merge|--no-merg)
      return 0
      ;;
    --points-at|--points-a|--points-|--points|--point|--poin|--poi|--po|--p)
      return 0
      ;;
    --set-upstream-to|--set-upstream-t|--set-upstream-)
      return 0
      ;;
    --set-upstream|--set-upstrea|--set-upstre|--set-upstr|--set-upst)
      return 0
      ;;
    --set-ups|--set-up|--set-u)
      return 0
      ;;
  esac
  return 1
}
is_destructive_branch_long_option() {
  local option="${1%%=*}"
  case "$option" in
    --d|--de|--del|--dele|--delet|--delete|--mo|--mov|--move)
      return 0
      ;;
  esac
  return 1
}
contains_destructive_branch_option() {
  local command_text="$1"
  local -a tokens
  local encoded_tokens
  encoded_tokens="$(tokenize_command "$command_text")" || return 1
  IFS=$'\x1f' read -ra tokens <<< "$encoded_tokens"
  local search_index=0
  local branch_idx
  while branch_idx="$(git_subcommand_index "$command_text" branch "$search_index")"; do
    search_index=$((branch_idx + 1))
    local idx
    for ((idx=branch_idx+1; idx<${#tokens[@]}; idx++)); do
      local token="${tokens[idx]}"
      is_shell_separator_token "$token" && break
      if branch_option_consumes_value "$token"; then
        idx=$((idx + 1))
        continue
      fi
      if [[ "$token" == *=* ]] \
        && branch_option_consumes_value "${token%%=*}"; then
        continue
      fi
      if [[ "$token" == -d || "$token" == -D || "$token" == -m || "$token" == -M ]] \
        || is_destructive_branch_long_option "$token"; then
        return 0
      fi
      if [[ "$token" == -?* && "$token" != --* ]]; then
        local short_options="${token#-}"
        local option_index
        for ((option_index=0; option_index<${#short_options}; option_index++)); do
          local option_letter="${short_options:option_index:1}"
          case "$option_letter" in
            d|D|m|M)
              return 0
              ;;
            c|C|u)
              # These options consume the rest of an attached token as their
              # value, so letters in that value are not clustered flags.
              break
              ;;
          esac
        done
      fi
    done
  done
  return 1
}
contains_destructive_update_ref() {
  local command_text="$1"
  local -a tokens
  local encoded_tokens
  encoded_tokens="$(tokenize_command "$command_text")" || return 1
  IFS=$'\x1f' read -ra tokens <<< "$encoded_tokens"
  local search_index=0
  local update_ref_idx
  while update_ref_idx="$(git_subcommand_index "$command_text" update-ref "$search_index")"; do
    search_index=$((update_ref_idx + 1))
    local delete_requested=false
    local idx
    for ((idx=update_ref_idx+1; idx<${#tokens[@]}; idx++)); do
      local token="${tokens[idx]}"
      is_shell_separator_token "$token" && break
      if [[ "$token" == "--stdin" || "$token" == "-z" ]]; then
        return 0
      fi
      if [[ "$token" == "-d" ]]; then
        delete_requested=true
        continue
      fi
      if [[ "$delete_requested" == true && "$token" == refs/heads/* ]]; then
        return 0
      fi
    done
  done
  return 1
}
contains_forbidden_publish_or_review_action() {
  local command_text="$1"
  if [[ "$command_text" == *'$('* || "$command_text" == *'`'* ]] \
    && [[ "$command_text" == *"git push"* ]]; then
    return 0
  fi
  if git_subcommand_index "$command_text" push >/dev/null; then
    if contains_protected_destination_push "$command_text" \
      || contains_forbidden_push_option "$command_text"; then
      return 0
    fi
  fi
  local merge_idx
  if merge_idx="$(gh_pr_subcommand_index "$command_text" merge)"; then
    local -a merge_tokens
    local encoded_merge_tokens
    encoded_merge_tokens="$(tokenize_command "$command_text")" || return 1
    IFS=$'\x1f' read -ra merge_tokens <<< "$encoded_merge_tokens"
    local merge_option_index
    for ((merge_option_index=merge_idx+1; merge_option_index<${#merge_tokens[@]}; merge_option_index++)); do
      local merge_token="${merge_tokens[merge_option_index]}"
      if [[ "$merge_token" == ";" \
        || "$merge_token" == "&&" \
        || "$merge_token" == "||" \
        || "$merge_token" == "|" \
        || "$merge_token" == "&" \
        || "$merge_token" == ")" ]]; then
        break
      fi
      case "$merge_token" in
        --admin|--auto|--delete-branch|-d)
          return 0
          ;;
      esac
    done
  fi
  if gh_api_command "$command_text"; then
    # Only the complete bounded GraphQL request may receive an exception.
    if [[ "$command_text" == *"resolvereviewthread"* \
       || "$command_text" == *"addpullrequestreviewthreadreply"* ]]; then
      if python3 "$codex_repo_root/scripts/pr-reconciliation.py" "$raw_command" >/dev/null; then
        return 1
      fi
      return 0
    fi
    if [[ "$command_text" == *"resolve-review-thread"* \
       || "$command_text" == *"addpullrequestreview"* \
       || "$command_text" == *"/pulls/"*"/reviews"* \
       || "$command_text" == *"/pulls/"*"/comments"* \
       || "$command_text" == *"/issues/"*"/comments"* ]]; then
      return 0
    fi
  fi
  return 1
}
command_lc="$(printf '%s' "$raw_command" | tr '[:upper:]' '[:lower:]')"
home_canon="$HOME"
if [[ -d "$HOME" ]]; then
  home_canon="$(cd -P "$HOME" && pwd -P)"
fi
home_lc="$(printf '%s' "$home_canon" | tr '[:upper:]' '[:lower:]')"
block_reason=""
is_git_no_verify_bypass=false
canonicalize_edit_target() {
  local target="$1"
  local base_dir="${_command_cwd:-$PWD}"
  python3 -I -S - "$base_dir" "$target" <<'PY'
import sys
from pathlib import Path

base = Path(sys.argv[1]).expanduser()
target = Path(sys.argv[2]).expanduser()
if not target.is_absolute():
    target = base / target
print(target.resolve(strict=False))
PY
}
is_sensitive_edit_target() {
  local target="$1"
  local target_lc
  target_lc="$(printf '%s' "$target" | tr '[:upper:]' '[:lower:]')"
  if [[ "$target_lc" == "~/.ssh"* \
     || "$target_lc" == ".ssh/"* \
     || "$target_lc" == ".ssh" \
     || "$target_lc" == "~/.codex/auth"* \
     || "$target_lc" == ".codex/auth"* \
     || "$target_lc" == "/etc/"* \
     || "$target_lc" == "/etc" ]]; then
    return 0
  fi
  local canonical_lc
  canonical_lc="$(canonicalize_edit_target "$target" | tr '[:upper:]' '[:lower:]')"
  [[ "$canonical_lc" == "${home_lc}/.ssh"* \
    || "$canonical_lc" == "${home_lc}/.codex/auth"* \
    || "$canonical_lc" == "/etc/"* \
    || "$canonical_lc" == "/etc" \
    || "$canonical_lc" == "/private/etc/"* \
    || "$canonical_lc" == "/private/etc" ]]
}
contains_direct_auth_material_access() {
  local command_text="$1"
  local analysis_result
  # Heredoc bytes from a known data consumer are not executable shell text.
  # Unsupported consumers or expansions remain a denial, never an empty scan.
  if ! command_text="$(python3 -I -S "$hook_dir/destructive-git-operation.py" --prepare-literals "$command_text")"; then
    return 0
  fi
  analysis_result="$(python3 -I -S - "$command_text" "$HOME" "$_command_cwd" "$codex_repo_root/scripts/pr-reconciliation.py" "$codex_repo_root/scripts/run-auth-backed.sh" <<'PY'
from __future__ import annotations

import fnmatch
import os
import posixpath
import re
import runpy
import shlex
import sys

command_text = sys.argv[1]
home = sys.argv[2]
home_lc = home.lower()
command_cwd = sys.argv[3]

policy = runpy.run_path(sys.argv[4])
wrapper_canonical = os.path.realpath(sys.argv[5]).lower()
def command_position(segment, function_names=()):
    value_options = {"env": {"-u", "--unset", "-C", "--chdir"}, "sudo": {"-u", "--user", "-g", "--group", "-h", "--host", "-p", "--prompt", "-C", "--close-from", "-R", "--chroot", "-D", "--chdir"}, "command": set(), "builtin": set(), "exec": {"-a"}, "time": set()}
    index = 0
    lookup_functions = True
    while index < len(segment):
        token = segment[index]
        if token in {"!", "if", "while", "until", "then", "do", "else", "elif", "{"} or re.match(r"[A-Za-z_][A-Za-z0-9_]*\+?=", token):
            index += 1
            continue
        executable = posixpath.basename(token)
        if lookup_functions and token in function_names and (executable in value_options or executable in {"bash", "sh", "zsh"} or is_canonical_wrapper(token)) and index + 1 < len(segment):
            raise ValueError("Uninspectable execution function")
        if executable in {"nice", "nohup", "timeout", "gtimeout", "eval"}:
            raise ValueError("Uninspectable execution wrapper")
        if executable not in value_options:
            break
        if executable in {"command", "builtin", "env", "sudo"}:
            lookup_functions = False
        index += 1
        while index < len(segment) and segment[index].startswith("-"):
            option = segment[index]
            if executable == "exec" and option != "--" and not re.fullmatch(r"-(?:[cl]+|a.*)", option) or executable == "time" and option not in {"--", "-p"}:
                raise ValueError("Uninspectable execution prefix option")
            index += 1 + int(option in value_options[executable])
            if option == "--":
                break
    return index


def command_segments(command: str, depth: int = 0, inherited_functions=frozenset()):
    """Inspect executable substitutions and shell payloads, retaining outer segments."""
    if depth > 4:
        raise ValueError("Uninspectable shell depth")
    substitutions = policy["substitution_commands"](command)
    if substitutions is None:
        raise ValueError("Uninspectable command substitution")
    lexer = shlex.shlex(policy["protect_quoted_punctuation"](command), posix=True, punctuation_chars=";&|<>()\n")
    lexer.whitespace, lexer.whitespace_split, lexer.commenters = " \t\r", True, ""
    tokens = list(lexer)
    function_names = inherited_functions | policy["declared_functions"](tokens)
    for substitution in substitutions:
        yield from command_segments(substitution, depth + 1, function_names)
    segments, current = [], []
    for raw in tokens:
        if raw and all(char in ";&|<>()\n" for char in raw):
            segments.append(current)
            current = []
        else:
            current.append(policy["decode_protected_punctuation"](raw))
    segments.append(current)
    for segment in segments:
        yield segment, function_names
        wrapper_at = wrapper_index(segment, function_names)
        if wrapper_at is not None:
            args = segment[wrapper_at + 1:]
            while args and args[0] in {"--env-file", "--environment", "--require-env", "--canary", "--require-environment", "--help", "-h"}:
                args = args[1:] if args[0] in {"--require-environment", "--help", "-h"} else args[2:]
            if args and args[0] == "--":
                yield from command_segments(shlex.join(args[1:]), depth + 1)
            continue
        index = command_position(segment, function_names)
        if index >= len(segment) or posixpath.basename(segment[index]) not in {"bash", "sh", "zsh"}:
            continue
        index += 1
        while index < len(segment) and segment[index].startswith(("-", "+")):
            option = segment[index]
            index += 1
            if option == "--":
                break
            if not option.startswith("--") and "c" in option[1:]:
                index += int(index < len(segment) and segment[index] == "--")
                if index >= len(segment):
                    raise ValueError("Missing shell payload")
                yield from command_segments(segment[index], depth + 1, function_names)
                break
            if option in {"-o", "+o", "-O", "+O"} or option.endswith(("o", "O")) and not option.startswith("--"):
                index += 1


def expanded_token(token: str) -> str:
    token = token.strip(" \t\r\n'\";,()").replace("${HOME}", home).replace("$HOME", home)
    return f"{home}/{token[2:]}" if token.startswith("~/") else token


def normalized_token(token: str) -> str:
    return posixpath.normpath(expanded_token(token)).lower()


def pattern_recipients(path: str) -> list[str] | None:
    """Inspect bounded pathname metadata; never read selected files or FIFOs."""
    recipients = ["/"]
    visited = 0
    for part in path.split("/")[1:]:
        if "**" in part:
            return None
        pattern = "*" if "[:" in part or "{" in part or "}" in part else part
        if not any(char in pattern for char in "*?["):
            recipients = [posixpath.join(parent, part) for parent in recipients]
            continue
        matches = []
        for parent in recipients:
            try:
                with os.scandir(parent) as entries:
                    for entry in entries:
                        visited += 1
                        if visited > 512:
                            return None
                        if fnmatch.fnmatchcase(entry.name, pattern):
                            matches.append(entry.path)
            except OSError:
                continue
        recipients = matches
    return recipients


def is_auth_path(token: str) -> bool:
    expanded = expanded_token(token)
    # An unresolved pattern may select a symlink. Collapsing a later '..'
    # would discard its protected destination, so reject that ambiguity.
    unresolved_pattern = False
    for part in expanded.split("/"):
        if part == ".." and unresolved_pattern:
            return True
        if any(char in part for char in "*?[{}"):
            unresolved_pattern = True
    normalized = normalized_token(token)
    joined = posixpath.join(command_cwd, expanded) if command_cwd else expanded
    candidates = {normalized, os.path.realpath(joined).lower()}
    if unresolved_pattern:
        recipients = pattern_recipients(joined if joined.startswith("/") else posixpath.join(os.getcwd(), joined))
        if recipients is None:
            return True
        candidates.update(os.path.realpath(path).lower() for path in recipients)
    if command_cwd and not normalized.startswith("/"):
        candidates.add(posixpath.normpath(posixpath.join(command_cwd, normalized)).lower())
    # Also compare unresolved spellings, including currently absent recipients.
    # Conservatively include auth descendants when a protected prefix matches.
    for candidate in candidates:
        if not candidate.startswith("/"):
            continue
        # fnmatch is not a shell parser: POSIX classes and brace expansions
        # must not become bypasses. Treat their whole path component as unknown.
        candidate = "/".join(
            "*" if "[:" in part or "{" in part or "}" in part else part
            for part in candidate.split("/")
        )
        if any(char in candidate for char in "*?["):
            pattern_parts = candidate.split("/")
            env_parts = f"{home_lc}/.codex/.env".split("/")
            if len(pattern_parts) == len(env_parts) and all(
                fnmatch.fnmatchcase(part, pattern)
                for part, pattern in zip(env_parts, pattern_parts)
            ):
                return True
            auth_parts = f"{home_lc}/.codex/auth".split("/")
            if len(pattern_parts) >= len(auth_parts) and all(
                fnmatch.fnmatchcase(part, pattern)
                for part, pattern in zip(auth_parts, pattern_parts)
            ):
                return True
    return any(
        candidate == f"{home_lc}/.codex/.env"
        or candidate.endswith("/.codex/.env")
        or candidate.startswith(f"{home_lc}/.codex/auth")
        or "/.codex/auth" in candidate
        for candidate in candidates
    )


def is_canonical_wrapper(token: str) -> bool:
    expanded = expanded_token(token)
    paths = {expanded, os.path.join(command_cwd, expanded)} if command_cwd and not os.path.isabs(expanded) else {expanded}
    documented = wrapper_canonical
    return normalized_token(token) == documented or any(os.path.realpath(path).lower() == wrapper_canonical for path in paths)


def wrapper_index(tokens, function_names=()) -> int | None:
    idx = command_position(tokens, function_names)
    if idx < len(tokens) and is_canonical_wrapper(tokens[idx]):
        return idx
    if idx < len(tokens) and posixpath.basename(tokens[idx]) in {"bash", "sh", "zsh"}:
        idx += 1
        while idx < len(tokens) and tokens[idx].startswith("-"):
            idx += 1
        if idx < len(tokens) and is_canonical_wrapper(tokens[idx]):
            return idx
    return None


try:
    for tokens, function_names in command_segments(command_text):
        wrapper_at = wrapper_index(tokens, function_names)
        skip_indices: set[int] = set()
        if wrapper_at is not None:
            idx = wrapper_at + 1
            while idx < len(tokens):
                if tokens[idx] == "--" or all(char in ";&|<>()\n" for char in tokens[idx]):
                    break
                if tokens[idx] == "--env-file" and idx + 1 < len(tokens):
                    if normalized_token(tokens[idx + 1]) == f"{home_lc}/.codex/.env":
                        skip_indices.add(idx + 1)
                idx += 1

        for idx, token in enumerate(tokens):
            if idx in skip_indices:
                continue
            if is_auth_path(token):
                raise SystemExit(0)
except ValueError:
    raise SystemExit(1)
print("no-auth-material-access")
PY
)" || return 0
  [[ "$analysis_result" != "no-auth-material-access" ]]
}
if [[ "$_command_cwd" == "__codex_invalid_cwd__" ]]; then
  block_reason="Blocked uninspectable working directory transport."
elif [[ "$tool_name" == "apply_patch" || "$tool_name" == "Edit" || "$tool_name" == "Write" ]]; then
  if [[ -z "$edit_targets" ]]; then
    block_reason="Blocked edit tool without inspectable path target."
  else
    IFS=$'\x1e' read -r -a target_list <<<"$edit_targets"
    for edit_target in "${target_list[@]}"; do
      if is_sensitive_edit_target "$edit_target"; then
        block_reason="Blocked edit tool targeting sensitive credential or system configuration paths."
        break
      fi
    done
  fi
elif [[ "$tool_name" != "Bash" ]]; then
  run_ok
  exit 0
elif contains_direct_auth_material_access "$raw_command"; then
  block_reason="Blocked direct or uninspectable auth material access. Use codex/scripts/run-auth-backed.sh --env-file ~/.codex/.env --canary NAME for a fixed-output check, or the wrapper for an explicitly required auth-backed command."
elif contains_git_commit_no_verify "$command_lc" || contains_git_push_no_verify "$command_lc"; then
  block_reason="Blocked git hook bypass flag (--no-verify/-n). Bypass is forbidden; run commit/push with normal hook enforcement."
  is_git_no_verify_bypass=true
elif contains_forbidden_publish_or_review_action "$command_lc"; then
  block_reason="Blocked publish/review-thread mutation that requires explicit human approval."
elif contains_destructive_branch_option "$command_lc" \
  || contains_destructive_update_ref "$command_lc"; then
  block_reason="Blocked local branch deletion or rename. Re-run only with explicit scoped intent and approval."
elif git_worktree_risk="$(hook_runtime_destructive_git_operation "$raw_command" "${_command_cwd:-$PWD}")"; then
  case "$git_worktree_risk" in
    reset-hard)
      block_reason="Blocked potentially destructive git reset --hard. Re-run with explicit scoped intent and confirmation."
      ;;
    checkout-paths|checkout-destructive)
      block_reason="Blocked destructive git checkout because it can discard local changes. Use a targeted non-destructive approach."
      ;;
    checkout-unresolved)
      block_reason="Cannot prove the checkout operand is a local revision. For a remote branch, use an explicit git checkout --track origin/branch operand; implicit branch guessing is unsupported."
      ;;
    broad-delete)
      block_reason="Blocked broad rm -rf target (root/home). Use a scoped path and confirm intent."
      ;;
    *)
      block_reason="Blocked unsupported shell command syntax because destructive intent cannot be ruled out."
      ;;
  esac
elif [[ "$command_lc" == *"| sh"* || "$command_lc" == *"| bash"* ]]; then
  block_reason="Blocked pipe-to-shell execution. Download and inspect scripts before execution."
fi
if [[ -n "$block_reason" ]]; then
  # Check for break-glass bypass for git push --no-verify only
  if [[ "$is_git_no_verify_bypass" == true ]] \
    && contains_git_push_no_verify "$command_lc" \
    && ! contains_git_commit_no_verify "$command_lc" \
    && ! contains_forbidden_publish_or_review_action "$command_lc"; then
    bypass_ack="${CODEX_HOOK_BYPASS_ACK:-}"
    bypass_reason="${CODEX_HOOK_BYPASS_REASON:-}"
    bypass_log="${CODEX_HOOK_BYPASS_LOG:-}"
    if [[ -n "$bypass_ack" && -n "$bypass_reason" && -n "$bypass_log" ]]; then
      # Break-glass bypass accepted - log and allow
      timestamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
      jq -cn \
        --arg event "git-hook-bypass-breakglass" \
        --arg timestamp "$timestamp" \
        --arg reason "$bypass_reason" \
        --arg command "$raw_command" \
        --arg session "$session_id" \
        --arg turn "$turn_id" \
        '{
          event: $event,
          timestamp: $timestamp,
          reason: $reason,
          command: $command,
          session_id: $session,
          turn_id: $turn
        }' >> "$bypass_log"
      jq -n \
        --arg reason "$bypass_reason" \
        '{
          hookSpecificOutput: {
            hookEventName: "PreToolUse",
            additionalContext: ("Break-glass bypass accepted for git push --no-verify. Reason: " + $reason)
          }
        }'
      exit 0
    fi
  fi
  run_block "$block_reason"
else
  run_ok
fi
