import re
import os
import runpy
import shlex
import signal
import subprocess
import sys
from pathlib import Path

SHELL = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/pr-reconciliation.py'))

SHELL_PUNCTUATION = ";&|(){}"
SHELL_SEPARATORS = {";", "&&", "||", "|", "|&", "&", "(", ")", "{", "}"}
COMMAND_PREDECESSORS = SHELL_SEPARATORS
QUOTED_SEPARATOR_PREFIX = "\x1e"
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\+?=.*", re.DOTALL)


def ansi_literal(command, start):
    """Decode a literal Bash ANSI-C word without evaluating shell input."""
    result, index = [], start + 2
    escapes = dict(zip("abefnrtv\\'\"", "\a\b\x1b\f\n\r\t\v\\'\""))
    while index < len(command):
        char = command[index]
        if char == "'":
            return shlex.quote(''.join(result).split('\0', 1)[0]), index + 1
        if char != "\\":
            result.append(char)
            index += 1
            continue
        index += 1
        if index >= len(command):
            break
        char = command[index]
        if char in escapes:
            result.append(escapes[char])
            index += 1
        elif char in {'x', 'u', 'U'}:
            count = {'x': 2, 'u': 4, 'U': 8}[char]
            match = re.match('[0-9a-fA-F]{1,' + str(count) + '}', command[index + 1:])
            if not match:
                raise ValueError('Invalid ANSI-C hex escape')
            result.append(chr(int(match[0], 16)))
            index += 1 + len(match[0])
        elif char in '01234567':
            match = re.match('[0-7]{1,3}', command[index:])
            result.append(chr(int(match[0], 8)))
            index += len(match[0])
        else:
            raise ValueError('Unsupported ANSI-C escape')
    raise ValueError('Unclosed ANSI-C quote')


def prepare_literals(command, opaque_transport=None):
    """Remove literal heredoc data before shell quote/substitution analysis."""
    output, pending, frames = [], [], []
    quote, word_start, index, simple_start = None, True, 0, 0
    while index < len(command):
        char = command[index]
        if quote is None and command.startswith(('<(', '>('), index):
            raise ValueError('Process substitution requires separate inspection')
        if char == '\\' and quote != "'" and index + 1 < len(command):
            output.append(command[index:index + 2])
            index += 2
            word_start = False
            continue
        if quote is None and char == '#' and word_start:
            end = command.find('\n', index)
            end = len(command) if end < 0 else end
            output.append(command[index:end])
            index = end
            continue
        if quote is None and char == '{':
            close = command.find('}', index + 1)
            if close >= 0 and (',' in command[index + 1:close] or '..' in command[index + 1:close]):
                raise ValueError('Brace expansion requires separate inspection')
        if quote is None and command.startswith("$'", index):
            value, index = ansi_literal(command, index)
            output.append(value)
            word_start = False
            continue
        if quote != "'" and command.startswith('$((', index) or quote is None and command.startswith('((', index):
            raise ValueError('Arithmetic shell syntax requires separate inspection')
        if quote != "'" and command.startswith('$(', index) and not command.startswith('$((', index):
            frames.append([quote, 1])
            output.append('$(')
            quote, word_start, index = None, True, index + 2
            simple_start = len(output)
            continue
        if quote is None and frames and char in '()':
            frames[-1][1] += 1 if char == '(' else -1
            if frames[-1][1] == 0:
                quote = frames.pop()[0]
            output.append(char)
            index += 1
            word_start = False
            continue
        if quote is None and command.startswith('<<<', index):
            if opaque_transport is not None:
                opaque_transport[0] = True
            output.append('<<<')
            index += 3
            word_start = True
            continue
        if quote is None and command.startswith('<<', index):
            if opaque_transport is not None:
                opaque_transport[0] = True
            prefix = shell_split(''.join(output[simple_start:]))
            executable = wrapper_command_index(prefix, 0, len(prefix))
            if executable >= len(prefix) or prefix[executable].rsplit('/', 1)[-1] not in {'cat', 'tee', 'printf'}:
                raise ValueError('Heredoc consumer may execute its input')
            start = index + 2
            strip_tabs = command[start:start + 1] == '-'
            start += int(strip_tabs)
            while start < len(command) and command[start] in ' \t':
                start += 1
            end, delimiter_quote, quoted = start, None, False
            while end < len(command):
                current = command[end]
                if current == '\\' and delimiter_quote != "'":
                    quoted, end = True, end + 2
                    continue
                if current in "'\"":
                    quoted = True
                    delimiter_quote = None if delimiter_quote == current else current if delimiter_quote is None else delimiter_quote
                elif delimiter_quote is None and current in ' \t\r\n;&|<>()':
                    break
                end += 1
            delimiter_word = command[start:end]
            if delimiter_word.startswith("$'"):
                delimiter_word, consumed = ansi_literal(delimiter_word, 0)
                if consumed != end - start:
                    raise ValueError('Mixed ANSI-C heredoc delimiter requires separate inspection')
            elif "$'" in delimiter_word and not delimiter_word.startswith(("'", '"')):
                raise ValueError('Mixed ANSI-C heredoc delimiter requires separate inspection')
            values = shlex.split(delimiter_word)
            if len(values) != 1 or not values[0] or delimiter_quote is not None:
                raise ValueError('Unsupported heredoc delimiter')
            pending.append((values[0], quoted, strip_tabs))
            output.append(' ')
            index = end
            continue
        if quote is None and pending and char in '|&':
            if command.startswith(('&&', '||'), index):
                output.append(command[index:index + 2])
                index += 2
                word_start, simple_start = True, len(output)
                continue
            raise ValueError('Heredoc pipeline requires separate inspection')
        if char in "'\"":
            quote = None if quote == char else char if quote is None else quote
        output.append(char)
        index += 1
        if char == '\n' and quote is None and pending:
            for delimiter, quoted, strip_tabs in pending:
                body = []
                while index < len(command):
                    end = command.find('\n', index)
                    end = len(command) if end < 0 else end + 1
                    line = command[index:end]
                    index = end
                    if not quoted and '\\\n' in line:
                        raise ValueError('Continued unquoted heredoc requires separate inspection')
                    if (line.lstrip('\t') if strip_tabs else line).rstrip('\n') == delimiter:
                        break
                    body.append(line)
                else:
                    raise ValueError('Unclosed heredoc')
                if not quoted and re.search(r'\$\(|`', ''.join(body).replace('\\\n', '')):
                    raise ValueError('Unquoted heredoc command expansion requires inspection')
            pending.clear()
        word_start = quote is None and char in ' \t\r\n;&|<>()'
        if quote is None and char in '\n;&|':
            simple_start = len(output)
    if pending:
        raise ValueError('Heredoc body is missing')
    return ''.join(output)


def shell_split(command, keep_redirections=False):
    """Reuse the packaged lexical boundary contract; retain literal markers."""
    protected = SHELL["protect_quoted_punctuation"](command)
    protected = re.sub(r'(?<![^\s;&|()])\d+(?=[<>])', '', protected)
    lexer = shlex.shlex(protected,
                        posix=True, punctuation_chars=";&|<>(){}")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    tokens = []
    for token in lexer:
        decoded = SHELL["decode_protected_punctuation"](token)
        if token != decoded and (decoded and all(char in ';&|<>(){}' for char in decoded) or "\ue100" in token):
            decoded = QUOTED_SEPARATOR_PREFIX + decoded
        tokens.append(decoded)
    if keep_redirections:
        return tokens
    executable = wrapper_command_index(tokens, 0, len(tokens))
    if executable < len(tokens) and tokens[executable].rsplit('/', 1)[-1] in {'bash', 'sh', 'zsh', 'dash', 'ksh'} and any(
            token in {'<', '<<<', '<&'} for token in tokens):
        raise ValueError('Shell input redirection requires separate inspection')
    arguments, index = [], 0
    while index < len(tokens):
        token = tokens[index]
        if token in {'<', '>', '>>', '>|', '<&', '>&', '&>', '&>>', '<<<'}:
            if index + 1 >= len(tokens):
                raise ValueError('Missing redirection target')
            index += 2
            continue
        if token and all(char in '<>' for char in token):
            raise ValueError('Unsupported redirection syntax')
        arguments.append(token)
        index += 1
    return arguments


def shell_payload_index(tokens, start=0):
    index = start + 1
    command_string = False
    while index < len(tokens):
        option = tokens[index]
        if option == '--':
            index += 1
            break
        if option in {"-o", "-O", "+o", "+O", "--rcfile", "--init-file"}:
            if index + 1 >= len(tokens):
                raise ValueError("Shell option requires a value")
            index += 2
            continue
        if option.startswith(("-o", "-O", "+o", "+O")) and len(option) > 2:
            index += 1
            continue
        if not option.startswith(("-", "+")) or option in SHELL_SEPARATORS:
            break
        if not option.startswith("--"):
            cluster = option[1:]
            values = cluster.count("o") + cluster.count("O")
            if index + 1 + values > len(tokens):
                raise ValueError("Shell option requires a value")
            command_string = command_string or option.startswith('-') and 'c' in cluster
            index += 1 + values
            continue
        if option not in {'--noprofile', '--norc', '--posix', '--restricted', '--verbose',
                          '--login', '--debugger', '--noediting', '--dump-po-strings', '--dump-strings'}:
            raise ValueError('Unknown shell invocation option requires separate inspection')
        index += 1
    if command_string:
        if index < len(tokens) and tokens[index] not in SHELL_SEPARATORS:
            return index
        raise ValueError("Shell command payload is missing")
    return None


def protect_search_literals(command):
    """Retain quoted/escaped expansion glyphs for search-operand admission."""
    markers = dict(zip('$`*?[]{}', (chr(value) for value in range(0xE200, 0xE208))))
    if any(marker in command for marker in markers.values()):
        raise ValueError('Reserved search-analysis marker in command')
    output, quote, index = [], None, 0
    while index < len(command):
        char = command[index]
        if char == '\\' and quote != "'" and index + 1 < len(command):
            following = command[index + 1]
            if following in markers:
                # Double quotes suppress globbing even when a backslash is
                # retained literally before the glob character by the shell.
                prefix = '\\' if quote == '"' and following not in '$`' else ''
                output.append(prefix + markers[following])
            else:
                output.append(command[index:index + 2])
            index += 2
            continue
        if char in "'\"":
            quote = None if quote == char else char if quote is None else quote
        if char in markers and (quote == "'" or quote == '"' and char not in '$`'):
            output.append(markers[char])
        else:
            output.append(char)
        index += 1
    return ''.join(output)


def inspect_search_arguments(executable, operands):
    """Keep search option values distinct from command-producing options."""
    if executable not in {'find', 'gfind', 'fd', 'fdfind'}:
        return
    fd_search = executable in {'fd', 'fdfind'}
    value_options = ({'--extension', '--exclude', '--type', '--max-depth', '--min-depth',
        '--exact-depth', '--threads', '--color', '--size', '--changed-within', '--changed-before',
        '--ignore-file', '--max-results', '--batch-size', '--base-directory', '--path-separator',
        '--search-path', '--and', '-e', '-E', '-t', '-d', '-j', '-c', '-S'} if fd_search else {
        '-name', '-iname', '-path', '-ipath', '-wholename', '-iwholename', '-regex', '-iregex',
        '-type', '-xtype', '-maxdepth', '-mindepth', '-newer', '-anewer', '-cnewer', '-newermt',
        '-mtime', '-mmin', '-ctime', '-cmin', '-atime', '-amin', '-size', '-user', '-group',
        '-uid', '-gid', '-perm', '-links', '-inum', '-samefile', '-fstype', '-lname', '-ilname'})
    consume_value = False
    for token in operands:
        if fd_search and not consume_value and token == '--':
            return
        if any(char in token for char in '$`*?[]{}'):
            raise ValueError('Expandable search operands require separate inspection')
        if consume_value:
            consume_value = False
            continue
        if not fd_search:
            if token in {'-exec', '-execdir', '-ok', '-okdir'}:
                raise ValueError('Search utility command execution requires separate inspection')
        elif token.startswith('--'):
            if token.split('=', 1)[0] in {'--exec', '--exec-batch'}:
                raise ValueError('Search utility command execution requires separate inspection')
        elif token.startswith('-'):
            for index, option in enumerate(token[1:], 1):
                if option in 'xX':
                    raise ValueError('Search utility command execution requires separate inspection')
                if '-' + option in value_options:
                    consume_value = index == len(token) - 1
                    break
            continue
        consume_value = token in value_options


def inspect_shell(command, depth=0, budget=None, opaque_transport=None):
    """Inspect every executed shell/substitution with the same bounded pipeline."""
    if budget is None:
        budget = [0]
    if opaque_transport is None:
        opaque_transport = [False]
    prepared = prepare_literals(command, opaque_transport)
    budget[0] += len(prepared)
    if depth >= 12 or budget[0] > 262144:
        raise ValueError("Shell inspection budget exceeded")
    if any(token in {'>', '>>', '>|', '&>', '&>>', '<<<'}
           for token in shell_split(prepared, keep_redirections=True)):
        opaque_transport[0] = True
    lexical_tokens = shell_split(prepared)
    if SHELL['declared_functions'](lexical_tokens):
        raise ValueError('Shell function execution requires separate inspection')
    for index, token in enumerate(lexical_tokens):
        if token in {'|', '|&'}:
            executable = wrapper_command_index(lexical_tokens, index + 1, len(lexical_tokens))
            if executable < len(lexical_tokens) and lexical_tokens[executable].rsplit('/', 1)[-1].lower() in {
                    'bash', 'sh', 'zsh', 'dash', 'ksh'}:
                raise ValueError('Pipeline-fed shell requires separate inspection')
    contexts = SHELL["command_contexts"](prepared)
    if contexts is None:
        raise ValueError("Unsupported shell syntax")
    expanded = []
    for context, substitutions, marker in contexts:
        tokens = [token.replace(marker, "${__codex_substitution__}") for token in shell_split(context)]
        control_prefix = 0
        while tokens and tokens[0] in {"!", "if", "while", "until", "then", "do", "else", "elif"}:
            tokens.pop(0)
            control_prefix += 1
        if not tokens:
            continue
        if ASSIGNMENT.fullmatch(tokens[0]) and any(unsafe_git_environment(token) for token in tokens
                                                  if ASSIGNMENT.fullmatch(token)):
            raise ValueError('Sensitive Git environment assignment')
        executable_index = wrapper_command_index(tokens, 0, len(tokens))
        if executable_index < len(tokens):
            if any(char in tokens[executable_index] for char in '$`*?[{~'):
                raise ValueError('Dynamic executable requires separate inspection')
            executable = tokens[executable_index].rsplit("/", 1)[-1].lower()
            if executable == 'rg':
                value_options = {'--regexp', '--file', '--pre-glob', '--dfa-size-limit', '--encoding',
                    '--engine', '--max-count', '--regex-size-limit', '--threads', '--glob', '--iglob',
                    '--ignore-file', '--max-depth', '--max-filesize', '--type', '--type-not',
                    '--type-add', '--type-clear', '--after-context', '--before-context', '--color',
                    '--colors', '--context', '--context-separator', '--field-context-separator',
                    '--field-match-separator', '--hyperlink-format', '--max-columns',
                    '--path-separator', '--replace', '--sort', '--sortr', '--generate'}
                consume_value = False
                for operand in tokens[executable_index + 1:]:
                    if consume_value:
                        consume_value = False
                        continue
                    if operand == '--':
                        break
                    if operand.split('=', 1)[0] in {'--pre', '--hostname-bin'}:
                        raise ValueError('Search utility command execution requires separate inspection')
                    if operand in value_options:
                        consume_value = True
                    elif operand.startswith('-') and not operand.startswith('--'):
                        for position, flag in enumerate(operand[1:], 1):
                            if flag in 'efEmjgdtTABCMr':
                                consume_value = position == len(operand) - 1
                                break
                if consume_value:
                    raise ValueError('Missing search option value')
            if executable in {'find', 'gfind', 'fd', 'fdfind'}:
                search_tokens = [token.replace(marker, "${__codex_substitution__}")
                                 for token in shell_split(protect_search_literals(context))]
                inspect_search_arguments(executable, search_tokens[control_prefix + executable_index + 1:])
            if executable == 'tee':
                opaque_transport[0] = True
            if executable in {"bash", "sh", "zsh", "dash", "ksh"}:
                payload = shell_payload_index(tokens, executable_index)
                if payload is not None:
                    expanded.extend(inspect_shell(tokens[payload], depth + 1, budget, opaque_transport))
                    expanded.append(";")
                elif opaque_transport[0] or any(re.search(r'(?i)(?:^|[\s/;|&()])git(?:\s|$)', value)
                                                for value in tokens[executable_index + 1:]):
                    raise ValueError('File-backed shell after opaque data transport requires separate inspection')
            if executable not in {'git', 'printf', 'echo', 'cat', ':', 'true', 'false', 'test', '[',
                    'find', 'gfind', 'fd', 'fdfind', 'bash', 'sh', 'zsh', 'dash', 'ksh',
                    'export', 'declare', 'typeset', 'readonly', 'rg', 'grep', 'egrep', 'fgrep'} and any(
                    re.search(r'(?i)(?:^|[\s/;|&()])(?:git|rm)(?:\s|$)', value)
                    for value in tokens[executable_index + 1:]):
                raise ValueError('Unparsed utility with embedded Git command requires separate inspection')
            if executable in {"export", "declare", "typeset", "readonly"} and any(
                    unsafe_git_environment(token, bare=True) for token in tokens[executable_index + 1:]):
                raise ValueError("Program-valued Git environment mutation")
        expanded.extend(tokens)
        expanded.append(";")
        for payload in substitutions:
            expanded.extend(inspect_shell(payload, depth + 1, budget, opaque_transport))
            expanded.append(";")
    return expanded


def wrapper_command_index(tokens, start, limit):
    index = start
    while index < limit and ASSIGNMENT.fullmatch(tokens[index]):
        index += 1
    while index < limit:
        if ASSIGNMENT.fullmatch(tokens[index]):
            index += 1
            continue
        if tokens[index].isdigit() and index + 1 < limit and tokens[index + 1] in {">", ">>", "<", ">&", "<&"}:
            index += 1
        if tokens[index] in {">", ">>", "<", ">&", "<&"}:
            if index + 1 >= limit:
                raise ValueError("Missing redirection target")
            index += 2
            continue
        executable = tokens[index].rsplit("/", 1)[-1].lower()
        if executable in {'busybox', 'toybox'}:
            index += 1
            if index >= limit or tokens[index].startswith('-'):
                raise ValueError('Multicall utility needs a literal applet')
            continue
        if executable in {"eval", "xargs", "source", ".", "trap", "alias", "unalias", "coproc"}:
            raise ValueError("Unsupported command-producing wrapper")
        if executable == "nohup":
            index += 1
            if index < limit and tokens[index] == "--":
                index += 1
            continue
        if executable == "nice":
            index += 1
            while index < limit and tokens[index].startswith('-'):
                token = tokens[index]
                if token == '--':
                    index += 1
                    break
                if token in {'-n', '--adjustment'}:
                    if index + 1 >= limit or not re.fullmatch(r'[+-]?[0-9]+', tokens[index + 1]):
                        raise ValueError('Unsupported nice adjustment')
                    index += 2
                elif re.fullmatch(r'(?:-n|--adjustment=)[+-]?[0-9]+|-[0-9]+', token):
                    index += 1
                else:
                    raise ValueError('Unsupported nice option')
            continue
        if executable == 'caffeinate':
            index += 1
            while index < limit and tokens[index].startswith('-'):
                token = tokens[index]
                index += 1
                if token == '--':
                    break
                for offset, option in enumerate(token[1:], 1):
                    if option in 'dimsu':
                        continue
                    if option not in 'tw':
                        raise ValueError('Unsupported caffeinate option')
                    if offset == len(token) - 1:
                        if index >= limit or not tokens[index].isdigit():
                            raise ValueError('Missing caffeinate option value')
                        index += 1
                    elif not token[offset + 1:].isdigit():
                        raise ValueError('Unsupported caffeinate option value')
                    break
            continue
        if executable in {"timeout", "gtimeout"}:
            index += 1
            while index < limit and tokens[index].startswith("-"):
                index += 2 if tokens[index] in {"-k", "-s", "--kill-after", "--signal"} else 1
            if index >= limit or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?[smhd]?", tokens[index]):
                raise ValueError("Unsupported timeout duration")
            index += 1
            continue
        if executable == "exec":
            index += 1
            while index < limit and tokens[index].startswith('-'):
                token = tokens[index]
                index += 1
                if token == '--':
                    break
                if token == '-':
                    raise ValueError('Unsupported exec option')
                for offset, option in enumerate(token[1:], 1):
                    if option in 'cl':
                        continue
                    if option != 'a':
                        raise ValueError('Unsupported exec option')
                    if offset == len(token) - 1:
                        if index >= limit or tokens[index] in SHELL_SEPARATORS:
                            raise ValueError('Missing exec argument zero')
                        index += 1
                    break
            if index >= limit:
                raise ValueError('Missing exec command')
            continue
        if executable == "time":
            index += 1
            while index < limit and tokens[index] in {"--", "-p", "-l", "-c"}:
                index += 1
            continue
        if executable == "env":
            index += 1
            while index < limit:
                token = tokens[index]
                if token.startswith(("-S", "--split-string")):
                    raise ValueError("Unsupported env split-string payload")
                if ASSIGNMENT.fullmatch(token):
                    if unsafe_git_environment(token):
                        raise ValueError('Sensitive Git environment assignment')
                    index += 1
                    continue
                if token == "--":
                    index += 1
                    break
                if token.startswith('-C') or token == '--chdir' or token.startswith('--chdir='):
                    raise ValueError('Directory-changing wrapper requires separate inspection')
                if token in {"-u", "--unset"}:
                    index += 2
                    continue
                if token.startswith('--unset=') or token.startswith('-u'):
                    index += 1
                    continue
                if token.startswith("-"):
                    if token not in {'-i', '--ignore-environment', '-0', '--null', '-v', '--debug'}:
                        raise ValueError('Unsupported env option')
                    index += 1
                    continue
                break
            continue
        if executable == "sudo":
            index += 1
            value_options = {
                "-C", "-D", "-R", "-g", "-h", "-p", "-u", "-T", "-r", "-t", "-U",
                "--chdir", "--chroot", "--close-from", "--group",
                "--host", "--prompt", "--user", "--command-timeout", "--role", "--type", "--other-user",
            }
            while index < limit:
                token = tokens[index]
                if token.startswith(('-D', '-R', '--chdir', '--chroot')):
                    raise ValueError('Directory-changing wrapper requires separate inspection')
                if token in {'-i', '-s', '--login', '--shell'}:
                    raise ValueError('Sudo shell payload requires separate inspection')
                if token == "--":
                    index += 1
                    break
                if token in value_options:
                    index += 2
                    continue
                if token.split('=', 1)[0] in value_options or token[:2] in value_options:
                    index += 1
                    continue
                if token.startswith("-"):
                    if token not in {'-n', '-E', '-H', '-k', '-K', '-S', '-b', '-P', '-v', '-l',
                                     '--non-interactive', '--preserve-env', '--set-home', '--reset-timestamp',
                                     '--remove-timestamp', '--stdin', '--background', '--preserve-groups',
                                     '--validate', '--list'}:
                        raise ValueError('Unsupported sudo option')
                    index += 1
                    continue
                break
            continue
        if executable in {"command", "builtin"}:
            index += 1
            while index < limit and tokens[index] in {"--", "-p"}:
                index += 1
            continue
        break
    return index


def command_executable_positions(tokens):
    positions, start = {}, 0
    for limit in range(len(tokens) + 1):
        if limit == len(tokens) or tokens[limit] in SHELL_SEPARATORS:
            positions[start] = wrapper_command_index(tokens, start, limit)
            start = limit + 1
    return positions


def is_git_command(tokens, index, start, positions):
    if tokens[index].rsplit("/", 1)[-1].lower() != "git":
        return False
    return positions[start] == index


def has_dynamic_git_config_environment(tokens, index, start):
    for token in tokens[start:index]:
        if unsafe_git_environment(token):
            return True
    return False


def unsafe_git_environment(token, bare=False):
    if not ASSIGNMENT.fullmatch(token) and not bare:
        return False
    name = token.split("=", 1)[0].rstrip("+")
    return name in {"GIT_CONFIG_PARAMETERS", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_NAMESPACE", "GIT_PAGER", "PAGER", "GIT_EXTERNAL_DIFF",
                    "GIT_EDITOR", "GIT_SEQUENCE_EDITOR", "GIT_SSH_COMMAND", "GIT_SSH"} or bool(
        re.fullmatch(r"GIT_CONFIG_(?:COUNT|KEY_[0-9]+|VALUE_[0-9]+)", name))


def checkout_force_option(token):
    if not token.startswith("-") or token.startswith("--"):
        return False
    for option in token[1:]:
        if option in {"b", "B"}:
            return False
        if option in "f23p":
            return True
    return False


def checkout_branch_option_needs_value(token):
    if not token.startswith('-') or token.startswith('--'):
        return False
    for index, option in enumerate(token[1:], 1):
        if option in 'bB':
            return index == len(token) - 1
        if option not in 'qdtl':
            return False
    return False


def unsafe_config_override(value, require_value=False):
    if require_value and "=" not in value:
        return True
    key = value.split("=", 1)[0].lower()
    return (not key or key.startswith(("alias.", "include.", "includeif.", "credential.", "filter.", "pager."))
            or key in {"core.pager", "core.editor", "core.sshcommand", "core.fsmonitor", "core.hookspath", "sequence.editor", "diff.external", "core.askpass", "core.gitproxy", "gpg.program", "gpg.ssh.program"}
            or key.startswith("diff.") and key.endswith((".command", ".textconv"))
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
            if any(char in tokens[index + 1] for char in '$`*?[{~'):
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
            if any(char in token for char in '$`*?[{~'):
                return "unsupported", None
            index += 1
            continue
        if token.startswith("-c") and token != "-c":
            if any(char in token for char in '$`*?[{~') or unsafe_config_override(token[2:]):
                return "unsupported", None
            index += 1
            continue
        if token.startswith("--config-env="):
            if any(char in token for char in '$`*?[{~') or unsafe_config_override(token.split("=", 1)[1], True):
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


def inspection_timeout(_signum, _frame):
    raise ValueError("Shell inspection time budget exceeded")


def known_checkout_ref(tokens, git_index, subcommand_index, operand, positions):
    # Never guess a ref in a different directory after shell state changes.
    start = 0
    for index, token in enumerate(tokens[:git_index]):
        if token in SHELL_SEPARATORS:
            start = index + 1
        elif token in {'cd', 'chdir', 'pushd', 'popd'} and positions[start] == index:
            return False
    environment = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()),
                   'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
                   'GIT_TERMINAL_PROMPT': '0', 'GIT_NO_LAZY_FETCH': '1',
                   'GIT_ALLOW_PROTOCOL': ''}
    # Presentation configuration cannot affect ref identity. In particular,
    # config-env values are unavailable in this deliberately restricted env.
    arguments, index = [], git_index + 1
    while index < subcommand_index:
        token = tokens[index]
        if token.startswith('--exec-path='):
            return False
        if token in {'-c', '--config-env'}:
            if tokens[index + 1].split('=', 1)[0].lower() != 'color.ui':
                arguments.extend(tokens[index:index + 2])
            index += 2
            continue
        if (token.startswith('--config-env=') and token.split('=', 2)[1].lower() == 'color.ui'
                or token.startswith('-c') and token[2:].split('=', 1)[0].lower() == 'color.ui'):
            index += 1
            continue
        arguments.append(token)
        index += 1
    try:
        capability = subprocess.run(['/usr/bin/git', '--no-lazy-fetch', '--version'],
            env=environment, capture_output=True, text=True, cwd='/', timeout=1, check=False)
        no_lazy_fetch = ['--no-lazy-fetch'] if capability.returncode == 0 else []
        if not no_lazy_fetch and not (capability.returncode in {128, 129}
                and capability.stderr.startswith('unknown option: --no-lazy-fetch')):
            return False
        prefix = ['/usr/bin/git', '--no-pager', *no_lazy_fetch, '-c', 'core.fsmonitor=false', *arguments]
        if not no_lazy_fetch:
            # Older Git has no lazy-fetch suppression option. Only prove refs
            # in ordinary repositories; deny all transport protocols as well.
            config = subprocess.run([*prefix, 'config', '--get-regexp',
                r'^(extensions\.partialclone|remote\..*\.(promisor|partialclonefilter))$'],
                env=environment, capture_output=True, text=True, cwd=command_cwd, timeout=1, check=False)
            if config.returncode != 1 or config.stdout:
                return False
        result = subprocess.run([*prefix, 'rev-parse', '--verify', '--end-of-options',
            operand + '^{commit}'], env=environment, capture_output=True, text=True,
            cwd=command_cwd, timeout=1, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and bool(re.fullmatch(r'[0-9a-f]{40,64}\n?', result.stdout))


signal.signal(signal.SIGALRM, inspection_timeout)
signal.alarm(3)

def inert_shell_form(command):
    return bool(re.fullmatch(r'mkdir -p /[A-Za-z0-9_./-]+/\{[A-Za-z0-9_-]+(?:,[A-Za-z0-9_-]+)+\}', command)
                or re.fullmatch(r'printf %s \$\(\([0-9 +*/%()-]+\)\)', command)
                or re.fullmatch(r'cat <\(printf [A-Za-z0-9_./ -]+\)', command))

if len(sys.argv) > 1 and sys.argv[1] == '--prepare-literals':
    try:
        if len(sys.argv[2]) > 1048576:
            raise ValueError('Shell transport input exceeds inspection budget')
        if inert_shell_form(sys.argv[2]):
            # Keep path-bearing forms visible to the independent auth scanner.
            print('mkdir -p ' + shlex.quote(sys.argv[2][9:])
                  if sys.argv[2].startswith('mkdir -p ') else 'true')
        else:
            print(prepare_literals(sys.argv[2]))
    except (ValueError, IndexError):
        raise SystemExit(2)
    raise SystemExit(0)

try:
    command = sys.argv[1]
    command_cwd = sys.argv[2] if len(sys.argv) > 2 else os.getcwd()
    if not Path(command_cwd).is_absolute():
        raise ValueError('Requested working directory must be absolute')
    if len(command) > 1048576:
        raise ValueError("Shell transport input exceeds inspection budget")
    if len(prepare_literals(command)) > 65536:
        raise ValueError("Shell input exceeds inspection budget")
    command_tokens = inspect_shell(command)
except (ValueError, IndexError):
    # Admit only complete, inert forms; never infer safety from an absent keyword.
    print("safe" if inert_shell_form(command) else "unsupported")
    raise SystemExit(0)

positions = command_executable_positions(command_tokens)
segment_start = 0
for git_index in range(len(command_tokens)):
    if command_tokens[git_index] in COMMAND_PREDECESSORS:
        segment_start = git_index + 1
        continue
    if command_tokens[git_index].rsplit('/', 1)[-1].lower() == 'rm' and positions[segment_start] == git_index:
        arguments = []
        for token in command_tokens[git_index + 1:]:
            if token in SHELL_SEPARATORS:
                break
            arguments.append(token)
        recursive = any(token in {'--recursive'} or token.startswith('-') and not token.startswith('--')
                        and any(char in token[1:] for char in 'rR') for token in arguments)
        force = any(token == '--force' or token.startswith('-') and not token.startswith('--')
                    and 'f' in token[1:] for token in arguments)
        if recursive and force:
            for target in (value for value in arguments if not value.startswith('-')):
                if any(char in target for char in '$`*?[{'):
                    print('unsupported')
                    raise SystemExit(0)
                try:
                    resolved = Path(target).expanduser()
                    if not resolved.is_absolute():
                        resolved = Path(command_cwd) / resolved
                    resolved = resolved.resolve()
                    home = Path.home().resolve()
                except (OSError, RuntimeError, ValueError):
                    print('unsupported')
                    raise SystemExit(0)
                if resolved == Path('/') or resolved == home or resolved in home.parents:
                    print('broad-delete')
                    raise SystemExit(0)
                # A preflight pathname cannot bind the later raw deletion inode.
                print('unsupported')
                raise SystemExit(0)
    if not is_git_command(command_tokens, git_index, segment_start, positions):
        continue
    if has_dynamic_git_config_environment(command_tokens, git_index, segment_start):
        print("unsupported")
        raise SystemExit(0)
    status, parsed = git_subcommand(command_tokens, git_index)
    if status == "unsupported":
        print("unsupported")
        raise SystemExit(0)
    if status != "command":
        continue
    subcommand, subcommand_index = parsed
    if subcommand == "config":
        arguments = []
        for token in command_tokens[subcommand_index + 1:]:
            if token in SHELL_SEPARATORS:
                break
            arguments.append(token)
        if not any(token in {"--get", "--get-all", "--get-regexp", "--list", "-l"} for token in arguments):
            if any(not token.startswith("-") and unsafe_config_override(token) for token in arguments):
                print("unsupported")
                raise SystemExit(0)
    options = True
    checkout_value = False
    checkout_operands = 0
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
        if checkout_value:
            checkout_value = False
            continue
        if subcommand == 'checkout' and (token == '--orphan' or checkout_branch_option_needs_value(token)):
            checkout_value = True
            continue
        if subcommand == "checkout" and token in {".", ".."}:
            print("checkout-paths")
            raise SystemExit(0)
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
            or token.startswith('--') and len(token) > 2
            and any(option.startswith(token) for option in ('--ours', '--theirs', '--patch'))
        ):
            print("checkout-destructive")
            raise SystemExit(0)
        if subcommand == 'checkout' and token.startswith('-'):
            ordinary = token in {'--quiet', '--detach', '--progress', '--no-progress', '--guess',
                                 '--no-guess', '--track', '--no-track', '--no-overlay'}
            if token.startswith('--track='):
                ordinary = token.split('=', 1)[1] in {'direct', 'inherit'}
            if not token.startswith('--'):
                ordinary = True
                for option in token[1:]:
                    if option in 'bB':
                        break
                    if option not in 'qdtl':
                        ordinary = False
                        break
            if not ordinary:
                print('unsupported')
                raise SystemExit(0)
        if subcommand == 'checkout' and not token.startswith('-'):
            checkout_operands += 1
            if checkout_operands > 1:
                print('checkout-paths')
                raise SystemExit(0)
            if not known_checkout_ref(command_tokens, git_index, subcommand_index, token, positions):
                print('checkout-unresolved')
                raise SystemExit(0)

signal.alarm(0)
print("safe")
