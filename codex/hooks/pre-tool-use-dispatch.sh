#!/usr/bin/env bash

set -euo pipefail

input_json="$(cat)"
dots_hook_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
python3 "$dots_hook_dir/../scripts/admit-hook-fixture.py" "$input_json" || exit $?
hook_dir="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

analysis_failure() {
  jq -n '{
    systemMessage: "PreToolUse dispatcher blocked because command analysis failed.",
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: "Required command analysis failed or returned an invalid route set."
    }
  }'
  exit 0
}

indirect_failure() {
  jq -n '{
    systemMessage: "PreToolUse blocked shell execution that is indirect, uninspectable or not admitted.",
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: "Blocked protected or uninspectable indirect shell execution, or a command not admitted by the active policy. For indirect commands, use direct syntax where possible. Direct syntax alone does not grant execution authority; use a supported route."
    }
  }'
  exit 0
}

if ! parsed="$(
  printf '%s' "$input_json" | python3 -I -S -c '
import json
import os
import re
import runpy
import shlex
import shutil
import stat
import sys

policy = runpy.run_path(sys.argv[1])
substitution_commands = policy["substitution_commands"]
command_contexts = policy["command_contexts"]
protect_quoted_punctuation = policy["protect_quoted_punctuation"]
decode_protected_punctuation = policy["decode_protected_punctuation"]
declared_functions = policy["declared_functions"]
repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(sys.argv[1]))))
payload = json.load(sys.stdin)
if not isinstance(payload, dict):
    raise TypeError("hook payload must be a JSON object")
tool_name = str(payload.get("tool_name", ""))
tool_input = payload.get("tool_input")
command = ""
if isinstance(tool_input, dict):
    command = str(tool_input.get("command", ""))
if not command:
    command = str(payload.get("command", ""))

route = {
    "safe": False,
    "pr": False,
    "commit": False,
    "scaffold": False,
    "unsafe": False,
}
shell_operators = {"&&", "||", ";", "|", "&", "(", ")", "{", "}", "\n"}
shell_punctuation = frozenset(";&|(){}\n")
control_boundaries = {"then", "do", "else", "elif"}
assignment = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=")


def tokenize(command_text):
    try:
        lexer = shlex.shlex(
            protect_quoted_punctuation(command_text),
            posix=True,
            punctuation_chars=";&|()\n",
        )
        # Preserve unquoted newlines as command boundaries. Quoted newlines stay
        # inside their token, and backslash-newline retains shell continuation
        # semantics rather than becoming a boundary.
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        return []


def has_expandable_dollar(command_text):
    # Regex anchors are data. Other dollars outside single quotes remain
    # conservative, including parameter expansions and dynamic executables.
    quote = None
    index = 0
    while index < len(command_text):
        char = command_text[index]
        if char == "\\" and quote != chr(39):
            index += 2
            continue
        if char in {chr(39), chr(34)}:
            quote = None if quote == char else char if quote is None else quote
        elif char == "$" and quote != chr(39):
            # A terminal dollar or one immediately before its closing double
            # quote has no expansion operand. ANSI-C quoting remains unsafe.
            if index + 1 < len(command_text) and command_text[index + 1] != quote:
                return True
        index += 1
    return False


def split_segments(tokens):
    segments, current = [], []
    for token in tokens:
        if token in shell_operators or (token in control_boundaries and not current) or (token and all(char in shell_punctuation for char in token)):
            if current: segments.append(current); current = []
        else: current.append(token)
    if current: segments.append(current)
    return segments

def process_isolated_segments(tokens):
    flags, saw, depth, after_pipe = [], False, 0, False
    for token in tokens:
        border = token in shell_operators or (token in control_boundaries and not saw) or (bool(token) and all(char in shell_punctuation for char in token))
        if not border:
            if not saw: flags.append(after_pipe or depth > 0); saw = True
            continue
        if saw:
            if token in {"|", "&"}: flags[-1] = True
            after_pipe, saw = token == "|", False
        depth += (token == "(") - (token == ")" and depth > 0)
        if token in {";", "&&", "||", "\n", "&", "then", "do", "else", "elif"}: after_pipe = False
    return flags

def segment_function_depths(tokens):
    depths, owners, declarations, current, depth, pending, skip_rparen = [], [], set(), [], 0, 0, False
    pending_name, last_name, last_segment, stack, frames = None, None, None, [], []
    for index, token in enumerate(tokens):
        border = token in shell_operators or (token in control_boundaries and not current) or (token and all(char in shell_punctuation for char in token))
        if not border: current.append(token); continue
        if current:
            depths.append(depth); owners.append(stack[-1] if stack else None); last_segment = len(depths) - 1
            if current[0] == "function" and len(current) > 1: pending, pending_name = 1, current[1]; declarations.add(last_segment)
            elif current and all(token in {"!", "if", "while", "until", "for", "select"} for token in current[:-1]): last_name = current[-1]
            current = []
        if skip_rparen and token == ")": skip_rparen = False
        elif token == "()" or (token == "(" and index + 1 < len(tokens) and tokens[index + 1] == ")"):
            pending, skip_rparen = max(pending, 1), token == "("; pending_name = pending_name or last_name
            if last_segment is not None: declarations.add(last_segment)
        elif token == "(" or token == "{":
            if pending: stack.append(pending_name); frames.append(True); pending, pending_name = pending - 1, None
            else: frames.append(False)
            depth += 1
        elif token in {"}", ")"} and depth:
            depth -= 1
            if frames and frames.pop() and stack: stack.pop()
        elif token in {";", "&&", "||", "&"} and pending and not depth: pending, pending_name = 0, None
    if current: depths.append(depth); owners.append(stack[-1] if stack else None)
    return depths, owners, declarations


def basename(token):
    return token.rsplit("/", 1)[-1]


def inspect_environment_mutation(tokens):
    home_override = False
    for token in tokens:
        name = decode_protected_punctuation(token).partition("=")[0].removesuffix("+")
        home_override |= name == "HOME"
        route["unsafe"] |= "[" in name or name in {"BASH_ENV", "ZDOTDIR", "ENV", "PATH", "PS4", "BASH_ALIASES", "BASH_CMDS", "OPTIND", "SECONDS", "RANDOM", "SRANDOM", "BASHPID", "HISTCMD", "CODEX_VALIDATION_PYTHON", "CODEX_VALIDATION_UV_PYTHON", "PYTHONPATH", "PYTHONHOME", "POSIXLY_CORRECT", "SHELLOPTS", "BASHOPTS"} or name.startswith("GIT_CONFIG_")
    return home_override

def printf_sets_home(operands):
    op_index = 0
    while op_index < len(operands) and operands[op_index].startswith("-") and operands[op_index] not in {"--", "-"}:
        option = operands[op_index]; op_index += 1
        if option.startswith("-v") and (destination := option[2:] or (operands[op_index] if op_index < len(operands) else None)) is not None:
            op_index += int(not option[2:] and destination is not None)
            if inspect_environment_mutation([destination]): return True
    return False

def unwrap(tokens, function_names):
    index = 0
    home_override = False
    lookup_functions = True
    while index < len(tokens):
        if assignment.match(tokens[index]):
            home_override |= inspect_environment_mutation([tokens[index]])
            index += 1
            continue
        if tokens[index] in {"!", "if", "while", "until"}:
            index += 1
            continue
        route["unsafe"] |= any(char in decode_protected_punctuation(tokens[index]) for char in "$`*?[{}")
        if lookup_functions and tokens[index] in function_names:
            route["unsafe"] |= index + 1 < len(tokens) and basename(tokens[index]) in {"command", "builtin", "env", "sudo"}
            break
        wrapper = basename(tokens[index])
        if wrapper in {"command", "builtin", "env", "sudo"}:
            lookup_functions = False
        if wrapper in {"nice", "nohup", "timeout", "gtimeout"}:
            route["unsafe"] = True
            return len(tokens), home_override
        if wrapper in {"command", "builtin"}:
            index += 1
            while index < len(tokens) and tokens[index].startswith("-"):
                index += 1
            continue
        if wrapper == "env":
            index += 1
            while index < len(tokens):
                token = tokens[index]
                if (token.startswith("-S") or token.startswith("--split-string")
                    or token.startswith("--chdir") or re.fullmatch(r"-[^-]*C.*", token)):
                    route["unsafe"] = True
                    return len(tokens), home_override
                if token == "--":
                    index += 1
                    break
                if assignment.match(token) or token.startswith("--unset=") or token.startswith("-u") and token != "-u":
                    home_override |= inspect_environment_mutation([token])
                    index += 1
                    continue
                if token in {"-u", "--unset"}:
                    index += 2
                    continue
                if token in {"-i", "--ignore-environment"}:
                    index += 1
                    continue
                if token.startswith("-"):
                    route["unsafe"] = True
                    return len(tokens), home_override
                break
            # GNU env with no command prints the resulting environment.
            if index >= len(tokens):
                route["unsafe"] = True
            continue
        if wrapper == "sudo":
            index += 1
            while index < len(tokens):
                token = tokens[index]
                if token == "--":
                    index += 1
                    break
                if token.startswith(("--chdir", "--chroot")) or re.fullmatch(r"-[^-]*[DR].*", token):
                    route["unsafe"] = True
                    return len(tokens), home_override
                if token in {"-u", "--user", "-g", "--group", "-h", "--host", "-C", "--close-from"}:
                    index += 2
                    continue
                if token.startswith("-"):
                    index += 1
                    continue
                break
            continue
        break
    return index, home_override


def git_subcommand(tokens, index):
    index += 1
    options_with_values = {"-c", "-C", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--exec-path", "--config-env"}
    while index < len(tokens):
        token = tokens[index]
        if token == "-c" or token.startswith("-c") or token == "--config-env" or token.startswith("--config-env="):
            route["unsafe"] = True
        if token in options_with_values:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        return token
    return ""


def gh_subcommand(tokens, index):
    index += 1
    options_with_values = {"-R", "--repo", "--hostname"}
    while index < len(tokens):
        token = tokens[index]
        if token in options_with_values:
            index += 2
            continue
        if token.startswith(("--repo=", "--hostname=")):
            index += 1
            continue
        if token.startswith("-"):
            index += 1
            continue
        return token, tokens[index + 1 :]
    return "", []


def same_owned_path(candidate, canonical):
    if candidate.casefold() != canonical.casefold():
        return False
    try:
        while os.path.samefile(candidate, canonical):
            if candidate == canonical:
                return True
            candidate, canonical = os.path.dirname(candidate), os.path.dirname(canonical)
    except OSError:
        pass
    return False


def owned_test(arg):
    if not re.fullmatch(r"codex(?:/scripts/tests/test_\w+\.py|\.scripts\.tests\.test_\w+(?:\.\w+){0,2})", arg):
        return False
    path = os.path.join(repo_root, "codex/scripts/tests", re.split(r"[/.]", arg)[3] + ".py")
    return os.path.isfile(path) and os.path.realpath(path) == path


def owned_unittest_args(args):
    if args[:2] != ["-m", "unittest"]:
        return False
    selectors, index = [], 2
    flags = {"-v", "--verbose", "-q", "--quiet", "-f", "--failfast", "-b", "--buffer"}
    while index < len(args):
        arg = args[index]
        if arg in flags:
            index += 1
            continue
        if arg == "--durations" or arg.startswith("--durations="):
            if arg == "--durations":
                index += 1
                if index == len(args):
                    return False
                value = args[index]
            else:
                value = arg.partition("=")[2]
            if not re.fullmatch(r"[0-9]{1,6}", value):
                return False
        elif owned_test(arg):
            selectors.append(arg)
        else:
            return False
        index += 1
    return bool(selectors)


def posix_options(options, enabled):
    index = 0
    while index < len(options):
        option = options[index]
        if option == "--" or not option.startswith(("-", "+")):
            break
        if option == "--posix":
            enabled = True
        if re.fullmatch(r"[-+][a-zA-Z]*o[a-zA-Z]*", option) and index + 1 < len(options):
            if options[index + 1] == "posix":
                enabled = option.startswith("-")
            index += 1
        index += 1
    return enabled


def inspect(command_text, depth=0, indirect=False, home_override=False, posix_mode=False, inherited_functions=frozenset(), inherited_home_functions=frozenset()):
    if depth > 3:
        route["unsafe"] = True
        return
    # Redirection grammar is outside the inspected command contract. Quoted
    # and escaped angle characters remain protected literal data.
    if any(char in protect_quoted_punctuation(command_text) for char in "<>"):
        route["unsafe"] = True
    contexts = command_contexts(command_text)
    if contexts is None:
        route["unsafe"] = True
        contexts = []
    tokens = tokenize(command_text)
    if not tokens:
        if protect_quoted_punctuation(command_text).strip():
            route.update({"pr": True, "commit": True, "scaffold": True})
        return
    function_names = inherited_functions | declared_functions(tokens)
    segments = []
    for context, substitutions, marker in contexts:
        consumed = 0
        for segment in split_segments(tokenize(context)):
            count = sum(token.count(marker) for token in segment)
            segments.append((segment, substitutions[consumed:consumed + count], marker))
            consumed += count
        route["unsafe"] |= consumed != len(substitutions)
    has_indirect_shell_syntax = (
        "$(" in command_text
        or "`" in command_text
        or ">" in command_text
        or "<" in command_text
    )
    simple_safe_git = (
        depth == 0
        and not has_indirect_shell_syntax
        and len(segments) == 1
        and not any(
            token in shell_operators
            or (bool(token) and all(char in shell_punctuation for char in token))
            or token in control_boundaries
            for token in tokens
        )
    )
    function_depths, function_owners, function_declarations = segment_function_depths(tokens)
    isolated_segments = process_isolated_segments(tokens)
    home_functions = set(inherited_home_functions)
    for segment_index, (segment, _substitutions, _marker) in enumerate(segments):
        if segment_index in function_declarations and segment:
            home_functions.discard(segment[1] if segment[0] == "function" and len(segment) > 1 else segment[-1])
        owner = function_owners[segment_index] if segment_index < len(function_owners) else None
        if not (function_depths[segment_index] if segment_index < len(function_depths) else 0) or not owner: continue
        index, scoped_home = unwrap(segment, function_names)
        exe = basename(segment[index]).lower() if index < len(segment) else ""
        if scoped_home or any(assignment.match(token) and inspect_environment_mutation([token]) for token in (segment if exe != "local" else segment[:index])): home_functions.add(owner)
        if exe in {"export", "readonly", "declare", "typeset"} and (inspect_environment_mutation(token for token in segment[index + 1:] if token != "HOME") or scoped_home): home_functions.add(owner)
        if exe == "printf" and printf_sets_home(segment[index + 1:]): home_functions.add(owner)
    changed = True
    while changed:
        changed = False
        for segment_index, (segment, _substitutions, _marker) in enumerate(segments):
            owner = function_owners[segment_index] if segment_index < len(function_owners) else None
            if not (function_depths[segment_index] if segment_index < len(function_depths) else 0) or not owner or owner in home_functions or segment_index in function_declarations: continue
            index, _scoped_home = unwrap(segment, function_names)
            if index < len(segment) and segment[index] in home_functions: home_functions.add(owner); changed = True
    body_home = False
    for segment_index, (segment, substitutions, marker) in enumerate(segments):
        function_depth = function_depths[segment_index] if segment_index < len(function_depths) else 0
        owner = function_owners[segment_index] if segment_index < len(function_owners) else None
        isolated = segment_index < len(isolated_segments) and isolated_segments[segment_index]
        body_home = body_home if function_depth else False
        active_home = home_override or body_home or (bool(owner) and owner in home_functions)
        def retain_home(value):
            nonlocal home_override, body_home
            if function_depth: body_home |= value
            elif not isolated: home_override |= value
        index, scoped_home = unwrap(segment, function_names)
        ordered_assignments = index >= len(segment) and all(assignment.match(token) or token in {"!", "if", "while", "until"} for token in segment)
        substitution_homes, assignment_home = [], active_home
        for token in segment:
            substitution_homes.extend([assignment_home if ordered_assignments else active_home] * token.count(marker))
            if ordered_assignments and assignment.match(token):
                assignment_home |= inspect_environment_mutation([token])
        for nested_command, nested_home in zip(substitutions, substitution_homes):
            if "$" in nested_command:
                route["unsafe"] = True
            inspect(nested_command, depth + 1, indirect=True, home_override=nested_home, posix_mode=posix_mode, inherited_functions=function_names, inherited_home_functions=frozenset(home_functions))
        if index >= len(segment):
            if scoped_home and ordered_assignments:
                retain_home(True)
            continue
        if segment[index] in home_functions and segment_index not in function_declarations:
            retain_home(True)
            active_home = True
        executable = basename(segment[index]).lower()
        route["unsafe"] |= (active_home or scoped_home) and segment[index] in function_names and segment_index not in function_declarations
        route["unsafe"] |= bool(substitutions) and marker in segment[index]
        tail = [token.lower() for token in segment[index + 1 :]]
        operands = segment[index + 1:]
        if posix_mode and executable in {":", "break", "continue", ".", "eval", "exec", "exit", "export", "readonly", "return", "set", "shift", "trap", "unset"} and not any(basename(token) in {"command", "builtin", "env"} for token in segment[:index] if not assignment.match(token)):
            retain_home(scoped_home)
        if executable == "set":
            posix_mode = posix_options(operands, posix_mode)
            if not operands:
                route["unsafe"] = True
        if executable in {"for", "select", "read", "let", "source", ".", "alias", "trap", "hash", "enable", "mapfile", "readarray", "compgen", "fc", "cd", "chdir", "pushd", "popd", "exec", "time", "printenv"}:
            route["unsafe"] = True
        if executable in {"export", "readonly", "declare", "typeset", "local"}:
            mutation = inspect_environment_mutation(token for token in operands if token != "HOME" or executable == "local")
            if executable == "local": body_home |= function_depth and (mutation or scoped_home)
            else: retain_home(scoped_home or mutation)
            has_name = any(not token.startswith(("-", "+")) or executable == "local" and token == "-" for token in operands)
            if not has_name or any(re.fullmatch(r"[-+][^-]*[aAinfFp].*", token) for token in operands):
                route["unsafe"] = True
        if executable == "printf": retain_home(printf_sets_home(operands))
        if executable == "eval":
            route["unsafe"] = True
            if index + 1 < len(segment):
                inspect(
                    " ".join(decode_protected_punctuation(token) for token in segment[index + 1 :]),
                    depth + 1, indirect=True,
                )
            else:
                route.update({"pr": True, "commit": True, "scaffold": True})
            continue
        # No image/execution qualification exists yet: do not admit this launcher,
        # including a copied same-name script. Other command policy remains intact.
        if executable == "run-sdk-offline-isolated.py" or (
            executable in {"python", "python3"}
            and any(os.path.basename(arg).casefold() == "run-sdk-offline-isolated.py" for arg in segment[index + 1:])
        ):
            route["unsafe"] = True
        if executable in {"bash", "zsh", "sh"}:
            route["unsafe"] |= executable == "zsh" and segment[index + 1:] != ["--version"]
            supplied = segment[index]
            approved = {f"/bin/{executable}", f"/usr/bin/{executable}", f"/opt/homebrew/bin/{executable}"}
            selected_interpreter = shutil.which(supplied) if "/" not in supplied else supplied
            route["unsafe"] |= selected_interpreter not in approved
            # Inspect the outer shell before relying on shlex-decoded payload
            # quotes: double-quoted outer payloads expand variables first.
            if has_expandable_dollar(command_text):
                route["unsafe"] = True
            inspected_payload = False
            shell_options = segment[index + 1 :]
            for option in shell_options:
                if not option.startswith("-") or option == "--":
                    break
                if re.sub(r"[-_]", "", option).casefold() in {"login", "interactive"} or (not option.startswith("--") and any(flag in option[1:] for flag in "ilx")):
                    route["unsafe"] = True
            for option_index, option in enumerate(segment[index + 1 :], start=index + 1):
                if not option.startswith("-") or option == "--":
                    break
                if not option.startswith("--") and "c" in option[1:]:
                    payload_index = option_index + 1
                    delimited = payload_index < len(segment) and segment[payload_index] == "--"
                    payload_index += delimited
                    if payload_index < len(segment) and (delimited or not segment[payload_index].startswith(("-", "+"))):
                        nested_command = decode_protected_punctuation(segment[payload_index])
                        if has_expandable_dollar(nested_command):
                            route["unsafe"] = True
                        inspect(nested_command, depth + 1, indirect=indirect or option_index > index + 1, home_override=active_home or scoped_home, posix_mode=posix_options(shell_options, executable == "sh"), inherited_functions=function_names, inherited_home_functions=frozenset(home_functions))
                    else:
                        route["unsafe"] = True
                    inspected_payload = True
                    break
            if not inspected_payload:
                # JSC-502: only owned validation entrypoints may stay direct.
                args = segment[index + 1:]
                while args and re.fullmatch(r"-[euxpnv]+", args[0]):
                    args = args[1:]
                if args and args[0] == "--":
                    args = args[1:]
                script = args[0] if args else ""
                cwd = (tool_input or {}).get("cwd") or (tool_input or {}).get("workdir") or payload.get("cwd") or os.getcwd()
                joined = os.path.join(cwd, script)
                spelling = os.path.abspath(joined)
                selected = os.path.realpath(joined)
                canonical_entry = spelling == selected and ".." not in script.split("/")
                if selected == os.path.join(repo_root, "codex/scripts/run-auth-backed.sh"):
                    route["unsafe"] |= executable != "bash" or not canonical_entry
                    args = args[1:]
                    while args and args[0] in {"--env-file", "--environment", "--require-env", "--canary", "--require-environment", "--help", "-h"}:
                        args = args[1:] if args[0] in {"--require-environment", "--help", "-h"} else args[2:]
                    if args:
                        if args[0] != "--":
                            route["unsafe"] = True
                        else:
                            child = shlex.join(decode_protected_punctuation(arg) for arg in args[1:])
                            inspect(child, depth + 1, indirect=True, home_override=active_home or scoped_home, inherited_home_functions=frozenset(home_functions))
                    continue
                governed = {os.path.join(repo_root, path) for path in (
                    "scripts/validate-codestyle.sh", "scripts/codex-preflight.sh",
                    "codex/scripts/verify-work.sh", "codex/scripts/validate-codex-hooks.sh",
                    "codex/scripts/audit-codex-symlinks.sh",
                    ".codex/skills/config-drift-guard/scripts/run_guard_checks.sh",
                )}
                # Bind case aliases through every differing directory component:
                # a hardlinked entrypoint alone does not identify sibling code.
                owned_script = os.path.isfile(selected) and any(
                    same_owned_path(selected, path)
                    for path in governed if os.path.isfile(path)
                )
                literal_script = owned_script and not any(arg.startswith("--repo-root") for arg in args[1:])
                validation_wrapper = os.path.join(repo_root, "codex/scripts/codex-validation-python-uv.sh")
                if os.path.isfile(selected) and os.path.isfile(validation_wrapper) and same_owned_path(selected, validation_wrapper):
                    literal_script = owned_unittest_args(args[1:])
                    literal_script |= len(args) > 1 and os.path.realpath(os.path.join(cwd, args[1])) == os.path.join(repo_root, "codex/scripts/validate-instruction-routing.py")
                    literal_script = literal_script and index == 0 and depth == 0 and len(segments) == 1 and os.path.realpath(cwd) == os.path.abspath(cwd) and same_owned_path(cwd.rstrip(os.sep) or os.sep, repo_root)
                # Registration and wrapper bytes do not authorise mutable candidate tests.
                # Literal Python admission stays limited to the canonical checkout above.
                route["unsafe"] |= literal_script and (active_home or scoped_home)
                literal_script = literal_script and executable == "bash" and canonical_entry
                if segment[index + 1:] != ["--version"] and not literal_script:
                    route["unsafe"] = True
            continue
        if executable == "git":
            subcommand = git_subcommand(segment, index)
            if indirect and subcommand not in {
                "status",
                "rev-parse",
                "for-each-ref",
                "ls-files",
                "rev-list",
            }:
                route["unsafe"] = True
            route["commit"] = route["commit"] or subcommand == "commit"
            route["safe"] = route["safe"] or (
                simple_safe_git
                and index == 0
                and subcommand in {"status", "rev-parse", "for-each-ref", "ls-files", "rev-list"}
            )
        elif executable == "gh":
            subcommand, remaining = gh_subcommand(segment, index)
            # A variable command name can otherwise hide a protected PR action.
            if has_expandable_dollar(decode_protected_punctuation(subcommand)):
                route.update({"pr": True, "unsafe": True})
            if substitutions and marker in subcommand:
                route.update({"pr": True, "unsafe": True})
            protected_gh = subcommand == "pr" or (
                subcommand == "api" and "graphql" in [token.lower() for token in remaining]
            )
            route["pr"] = route["pr"] or protected_gh
            if indirect and protected_gh:
                route["unsafe"] = True
        if executable in {"npm", "pnpm", "yarn", "bun"} and "create" in tail:
            route["scaffold"] = True
            route["unsafe"] = route["unsafe"] or indirect
        if executable in {"npx", "bunx", "uvx"} and any(
            token.startswith("create-")
            or re.match(r"^@[^/]+/create-", token)
            for token in tail
        ):
            route["scaffold"] = True
            route["unsafe"] = route["unsafe"] or indirect
        if executable in {"degit", "cookiecutter", "scaffold", "generate", "cargo-generate"}:
            route["scaffold"] = True
            route["unsafe"] = route["unsafe"] or indirect
        if executable == "django-admin" and "startproject" in tail:
            route["scaffold"] = True
            route["unsafe"] = route["unsafe"] or indirect
        if executable in {"ng", "nest"} and "new" in tail:
            route["scaffold"] = True
            route["unsafe"] = route["unsafe"] or indirect


if tool_name == "Bash":
    inspect(command)

print(
    "\t".join(
        "1" if route[key] else "0"
        for key in ("safe", "pr", "commit", "scaffold", "unsafe")
    )
)
' "$hook_dir/../scripts/pr-reconciliation.py"
)"; then
  analysis_failure
fi

if [[ ! "$parsed" =~ ^[01]$'\t'[01]$'\t'[01]$'\t'[01]$'\t'[01]$ ]]; then
  analysis_failure
fi

IFS=$'\t' read -r safe_route pr_route commit_route scaffold_route unsafe_route <<<"$parsed"

if [[ "$unsafe_route" == "1" ]]; then
  indirect_failure
fi

if [[ "$safe_route" == "1" ]]; then
  jq -n '{continue: true}'
  exit 0
fi

contexts=()

handler_failure() {
  local script_name="$1"
  local detail="$2"
  jq -n \
    --arg script "$script_name" \
    --arg detail "$detail" \
    '{
      systemMessage: "PreToolUse dispatcher blocked because a required policy handler failed.",
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: ("Required policy handler failed: " + $script + " (" + $detail + ")")
      }
    }'
  exit 0
}

run_guard() {
  local script_name="$1"
  local force_variable="${2:-}"
  local output
  local status
  if [[ -n "$force_variable" ]]; then
    if output="$(printf '%s' "$input_json" | env "$force_variable=1" bash "$hook_dir/$script_name" 2>/dev/null)"; then
      status=0
    else
      status=$?
    fi
  else
    if output="$(printf '%s' "$input_json" | bash "$hook_dir/$script_name" 2>/dev/null)"; then
      status=0
    else
      status=$?
    fi
  fi
  if [[ "$status" -ne 0 || -z "$output" ]]; then
    handler_failure "$script_name" "non-zero exit or empty output"
  fi
  if ! jq -e 'type == "object"' >/dev/null 2>&1 <<<"$output"; then
    handler_failure "$script_name" "invalid JSON output"
  fi
  if jq -e '.hookSpecificOutput.permissionDecision == "ask"' >/dev/null 2>&1 <<<"$output"; then
    handler_failure "$script_name" "unsupported ask decision"
  fi
  if ! jq -e '(.decision // "") != "block" and (.hookSpecificOutput.permissionDecision // "") != "deny"' >/dev/null <<<"$output"; then
    printf '%s\n' "$output"
    exit 0
  fi
  local additional_context
  additional_context="$(jq -r '.hookSpecificOutput.additionalContext // empty' <<<"$output")"
  if [[ -n "$additional_context" ]]; then
    contexts+=("$additional_context")
  fi
}

run_guard "pre-tool-use-guard.sh"
[[ "$pr_route" == "1" ]] && run_guard "pr-readiness-guard.sh"
[[ "$commit_route" == "1" ]] && run_guard "pre-commit-tests.sh" "CODEX_PRE_COMMIT_FORCE"
[[ "$scaffold_route" == "1" ]] && run_guard "pre-scaffold-typecheck.sh" "CODEX_PRE_SCAFFOLD_FORCE"

if [[ ${#contexts[@]} -gt 0 ]]; then
  context_blob="$(printf '%s\n' "${contexts[@]}")"
  jq -n --arg context "$context_blob" '{continue: true, hookSpecificOutput: {hookEventName: "PreToolUse", additionalContext: $context}}'
else
  jq -n '{continue: true}'
fi
