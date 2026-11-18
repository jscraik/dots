import re
import shlex
import sys

SHELL_PUNCTUATION = ";&|(){}"
SHELL_SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "{", "}"}
COMMAND_PREDECESSORS = SHELL_SEPARATORS | {
    "!", "do", "elif", "else", "if", "then", "until", "while"
}
QUOTED_SEPARATOR_PREFIX = "\x1e"
ESCAPED_SEPARATOR_MARKERS = {
    character: chr(0xE000 + index)
    for index, character in enumerate(SHELL_PUNCTUATION)
}
MARKER_SEPARATORS = {
    marker: character for character, marker in ESCAPED_SEPARATOR_MARKERS.items()
}
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*")


def shell_split(command):
    protected = []
    quote = None
    index = 0
    while index < len(command):
        character = command[index]
        if quote is None and character == chr(35) and (index == 0 or command[index - 1].isspace() or command[index - 1] in SHELL_PUNCTUATION):
            end = command.find("\n", index)
            index = len(command) if end < 0 else end
            continue
        if quote is not None:
            protected.append(ESCAPED_SEPARATOR_MARKERS.get(character, character))
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
        lexer = shlex.shlex(
            protected_command,
            posix=posix,
            punctuation_chars=SHELL_PUNCTUATION,
        )
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)

    tokens = lex(True)
    for index, token in enumerate(tokens):
        if token in MARKER_SEPARATORS:
            tokens[index] = QUOTED_SEPARATOR_PREFIX + MARKER_SEPARATORS[token]
            continue
        for marker, separator in MARKER_SEPARATORS.items():
            tokens[index] = tokens[index].replace(marker, separator)
    return tokens


def nested_command_payloads(command):
    payloads = []
    index = 0
    single_quote = False
    double_quote = False
    while index < len(command):
        character = command[index]
        if not single_quote and not double_quote and character == chr(35) and (index == 0 or command[index - 1].isspace() or command[index - 1] in SHELL_PUNCTUATION):
            end = command.find("\n", index)
            index = len(command) if end < 0 else end
            continue
        if character == "\\" and not single_quote:
            index += 2
            continue
        if character == "'" and not double_quote:
            single_quote = not single_quote
            index += 1
            continue
        if character == '"' and not single_quote:
            double_quote = not double_quote
            index += 1
            continue
        if character == "`" and not single_quote:
            end = index + 1
            payload = []
            while end < len(command):
                if command[end] == "\\" and end + 1 < len(command):
                    payload.extend((command[end], command[end + 1]))
                    end += 2
                    continue
                if command[end] == "`":
                    break
                payload.append(command[end])
                end += 1
            if end >= len(command):
                raise ValueError("unclosed backtick substitution")
            payloads.append("".join(payload))
            index = end + 1
            continue
        if (
            character == "$"
            and not single_quote
            and index + 1 < len(command)
            and command[index + 1] == "("
            and not command.startswith("$((", index)
        ):
            end = index + 2
            depth = 1
            nested_single_quote = False
            nested_double_quote = False
            while end < len(command) and depth:
                nested_character = command[end]
                if nested_character == "\\" and not nested_single_quote:
                    end += 2
                    continue
                if nested_character == "'" and not nested_double_quote:
                    nested_single_quote = not nested_single_quote
                elif nested_character == '"' and not nested_single_quote:
                    nested_double_quote = not nested_double_quote
                elif not nested_single_quote and not nested_double_quote:
                    if nested_character == "(":
                        depth += 1
                    elif nested_character == ")":
                        depth -= 1
                end += 1
            if depth:
                raise ValueError("unclosed command substitution")
            payloads.append(command[index + 2:end - 1])
            index = end
            continue
        index += 1
    return payloads


def shell_payload_index(tokens, start=0):
    index = start + 1
    while index < len(tokens):
        option = tokens[index]
        if option in {"-o", "-O", "--rcfile", "--init-file"}:
            if index + 1 >= len(tokens):
                raise ValueError("Shell option requires a value")
            index += 2
            continue
        if option.startswith(("-o", "-O")) and len(option) > 2:
            index += 1
            continue
        if not option.startswith("-") or option == "--" or option in SHELL_SEPARATORS:
            break
        if not option.startswith("--") and "c" in option[1:]:
            payload = index + 1
            if payload < len(tokens) and tokens[payload] == "--":
                payload += 1
            if payload < len(tokens) and tokens[payload] not in SHELL_SEPARATORS:
                return payload
            return None
        index += 1
    return None


def expose_nested_shell_commands(tokens, depth=0):
    if depth >= 4:
        raise ValueError("Nested shell inspection limit exceeded")
    expanded = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        expanded.append(token)
        start = index
        while start > 0 and tokens[start - 1] not in COMMAND_PREDECESSORS:
            start -= 1
        if (token.rsplit("/", 1)[-1] not in {"bash", "sh", "zsh"}
                or wrapper_command_index(tokens, start, index + 1) != index):
            index += 1
            continue
        command_index = shell_payload_index(tokens, index)
        if command_index is None:
            index += 1
            continue
        nested = shell_split(tokens[command_index])
        expanded.append(";")
        expanded.extend(expose_nested_shell_commands(nested, depth + 1))
        index = command_index + 1
    return expanded


def wrapper_command_index(tokens, start, limit):
    index = start
    while index < limit and ASSIGNMENT.fullmatch(tokens[index]):
        index += 1
    while index < limit:
        if index >= limit:
            break
        executable = tokens[index].rsplit("/", 1)[-1]
        if executable in {"exec", "time"}:
            index += 1
            while index < limit and tokens[index] in {"--", "-p", "-l", "-c"}:
                index += 1
            if executable == "exec" and index < limit and tokens[index] == "-a":
                index += 2
            continue
        if executable == "env":
            index += 1
            while index < limit:
                token = tokens[index]
                if ASSIGNMENT.fullmatch(token):
                    index += 1
                    continue
                if token == "--":
                    index += 1
                    break
                if token in {"-u", "--unset", "-C", "--chdir"}:
                    index += 2
                    continue
                if token.startswith("-"):
                    index += 1
                    continue
                break
            continue
        if executable == "sudo":
            index += 1
            value_options = {
                "-C", "-D", "-R", "-g", "-h", "-p", "-u",
                "--chdir", "--chroot", "--close-from", "--group",
                "--host", "--prompt", "--user",
            }
            while index < limit:
                token = tokens[index]
                if token == "--":
                    index += 1
                    break
                if token in value_options:
                    index += 2
                    continue
                if token.startswith("-"):
                    index += 1
                    continue
                break
            continue
        if executable == "command":
            index += 1
            while index < limit and tokens[index] in {"--", "-p"}:
                index += 1
            continue
        break
    return index


def is_git_command(tokens, index):
    if tokens[index].rsplit("/", 1)[-1].lower() != "git":
        return False
    start = index
    while start > 0 and tokens[start - 1] not in COMMAND_PREDECESSORS:
        start -= 1
    return wrapper_command_index(tokens, start, index + 1) == index


def has_dynamic_git_config_environment(tokens, index):
    start = index
    while start > 0 and tokens[start - 1] not in COMMAND_PREDECESSORS:
        start -= 1
    for token in tokens[start:index]:
        if not ASSIGNMENT.fullmatch(token):
            continue
        name = token.split("=", 1)[0]
        if name == "GIT_CONFIG_PARAMETERS" or re.fullmatch(
            r"GIT_CONFIG_(?:COUNT|KEY_[0-9]+|VALUE_[0-9]+)",
            name,
        ):
            return True
    return False


def checkout_force_option(token):
    if not token.startswith("-") or token.startswith("--"):
        return False
    for option in token[1:]:
        if option in {"b", "B"}:
            return False
        if option == "f":
            return True
    return False


def unsafe_config_override(value, require_value=False):
    if require_value and "=" not in value:
        return True
    key = value.split("=", 1)[0].lower()
    return (not key or key.startswith(("alias.", "include.", "includeif.", "credential.", "filter.", "pager."))
            or key in {"core.pager", "core.editor", "core.sshcommand", "core.fsmonitor", "core.hookspath", "sequence.editor", "diff.external"}
            or key.startswith("diff.") and key.endswith(".command")
            or key.startswith("merge.") and key.endswith(".driver"))


def git_subcommand(tokens, index):
    value_options = {
        "-C", "-c", "--config-env", "--git-dir", "--namespace",
        "--super-prefix", "--work-tree",
    }
    no_value_options = {
        "-P", "-p", "--bare", "--glob-pathspecs", "--icase-pathspecs",
        "--literal-pathspecs", "--no-lazy-fetch", "--no-literal-pathspecs",
        "--no-optional-locks", "--no-pager", "--no-replace-objects",
        "--noglob-pathspecs", "--paginate",
    }
    terminal_options = {
        "-h", "-v", "--exec-path", "--help", "--html-path",
        "--info-path", "--man-path", "--version",
    }
    index += 1
    while index < len(tokens) and tokens[index] not in SHELL_SEPARATORS:
        token = tokens[index]
        if token in terminal_options or token.startswith("--list-cmds="):
            return "terminal", None
        if token in value_options:
            if index + 1 >= len(tokens) or tokens[index + 1] in SHELL_SEPARATORS:
                return "unsupported", None
            if token in {"-c", "--config-env"} and unsafe_config_override(tokens[index + 1], token == "--config-env"):
                return "unsupported", None
            index += 2
            continue
        if (
            (token.startswith("-C") and token != "-C")
            or token.startswith("--attr-source=")
            or token.startswith("--exec-path=")
            or token.startswith("--git-dir=")
            or token.startswith("--namespace=")
            or token.startswith("--super-prefix=")
            or token.startswith("--work-tree=")
        ):
            index += 1
            continue
        if token.startswith("-c") and token != "-c":
            if unsafe_config_override(token[2:]):
                return "unsupported", None
            index += 1
            continue
        if token.startswith("--config-env="):
            if unsafe_config_override(token.split("=", 1)[1], True):
                return "unsupported", None
            index += 1
            continue
        if token in no_value_options:
            index += 1
            continue
        if token.startswith("-") or "$" in token or "`" in token:
            return "unsupported", None
        return "command", (token, index)
    return "none", None


try:
    command = sys.argv[1]
    if len(command) > 65536:
        raise ValueError("Shell input exceeds inspection budget")
    command_tokens = expose_nested_shell_commands(shell_split(command))
    pending_payloads = nested_command_payloads(command)
    inspected_bytes = len(command)
    while pending_payloads:
        payload = pending_payloads.pop(0)
        inspected_bytes += len(payload)
        if inspected_bytes > 262144:
            raise ValueError("Command substitution inspection budget exceeded")
        command_tokens.append(";")
        command_tokens.extend(expose_nested_shell_commands(shell_split(payload)))
        pending_payloads.extend(nested_command_payloads(payload))
except (ValueError, IndexError):
    print("unsupported")
    raise SystemExit(0)

for git_index in range(len(command_tokens)):
    if not is_git_command(command_tokens, git_index):
        continue
    if has_dynamic_git_config_environment(command_tokens, git_index):
        print("unsupported")
        raise SystemExit(0)
    status, parsed = git_subcommand(command_tokens, git_index)
    if status == "unsupported":
        print("unsupported")
        raise SystemExit(0)
    if status != "command":
        continue
    subcommand, subcommand_index = parsed
    options = True
    for token in command_tokens[subcommand_index + 1:]:
        if token in SHELL_SEPARATORS:
            break
        if token == "--":
            if subcommand == "checkout":
                print("checkout-paths")
                raise SystemExit(0)
            options = False
            continue
        if not options:
            continue
        if subcommand in {"checkout", "reset"} and (
            "$" in token or "`" in token or any(marker in token for marker in "*?[")
        ):
            print("unsupported")
            raise SystemExit(0)
        if subcommand == "reset" and token in {"--h", "--ha", "--har", "--hard"}:
            print("reset-hard")
            raise SystemExit(0)
        if subcommand == "checkout" and (
            token == "-f"
            or checkout_force_option(token)
            or token in {"--f", "--fo", "--for", "--forc", "--force"}
            or token == "--pathspec-from-file"
            or token.startswith("--pathspec-from-file=")
        ):
            print("checkout-destructive")
            raise SystemExit(0)

print("safe")
