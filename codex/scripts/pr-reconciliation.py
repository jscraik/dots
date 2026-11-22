"""Recognise bounded review-thread requests and executable shell substitutions."""

from __future__ import annotations

import re
import shlex
import sys

shell_punctuation = frozenset(";&|<>(){}\n")
protected_punctuation = {
    char: chr(0xE000 + index) for index, char in enumerate(sorted(shell_punctuation))
}
protected_punctuation.update(
    {char: chr(0xE101 + index) for index, char in enumerate(" \t\r")}
)
unprotected_punctuation = {value: key for key, value in protected_punctuation.items()}

READ_ONLY_PR_SUBCOMMANDS = frozenset({"checks", "diff", "list", "status", "view"})
UPDATE_PR_SUBCOMMANDS = frozenset(
    {"comment", "edit", "merge", "review"}
)
LIFECYCLE_PR_SUBCOMMANDS = frozenset({'close', 'ready', 'reopen'})


def pr_command_phase(subcommand):
    """Classify direct gh pr verbs, protecting unknown operations by default."""
    if subcommand in READ_ONLY_PR_SUBCOMMANDS:
        return "read_only"
    if subcommand == "create":
        return "create"
    if subcommand in LIFECYCLE_PR_SUBCOMMANDS:
        return 'lifecycle'
    if subcommand in UPDATE_PR_SUBCOMMANDS:
        return "update"
    return "unsupported_command"


def declared_functions(tokens):
    compound_body = re.compile(r"^(?:[({]|(?:if|for|while|until|case|select|\[\[)$)")
    controls = {"then", "do", "else", "elif", "!", "if", "while", "until", "time"}

    def starts_command(position):
        while position > 0:
            if tokens[position - 1] in controls:
                position -= 1
            elif position >= 2 and tokens[position - 2 : position] == ["time", "-p"]:
                position -= 2
            else:
                break
        return (
            position == 0
            or bool(tokens[position - 1])
            and all(char in ";&|(){}\n" for char in tokens[position - 1])
        )

    return {
        token
        for position, token in enumerate(tokens[:-1])
        if starts_command(position)
        and (
            tokens[position + 1].startswith("()")
            or tokens[position + 1 : position + 3] == ["(", ")"]
        )
    } | {
        tokens[position + 1]
        for position, token in enumerate(tokens[:-1])
        if token == "function"
        and starts_command(position)
        and compound_body.match(
            next((part for part in tokens[position + 2 :] if part.strip("\n")), "")
        )
    }


def protect_quoted_punctuation(
    command_text, *, comment_ranges=None, scan_substitutions=False
):
    """Protect syntax and optionally collect comment ranges in original offsets."""
    if any(marker in command_text for marker in (*unprotected_punctuation, "\ue100")):
        raise ValueError("reserved shell-analysis marker in command")
    protected, quote, at_word_start = [], None, True
    word_start, word_quoted = 0, False
    parenthesis_frames = []
    reserved = {
        "!",
        "if",
        "while",
        "until",
        "then",
        "do",
        "else",
        "elif",
        "for",
        "select",
        "case",
        "function",
        "time",
    }

    def finish_word() -> None:
        nonlocal word_start, word_quoted
        if word_quoted:
            try:
                tokens = shlex.split("".join(protected[word_start:]))
            except ValueError:
                tokens = []
            if len(tokens) == 1 and tokens[0] in reserved:
                protected.insert(word_start, "\ue100")
        word_start, word_quoted = len(protected), False

    index = 0
    while index < len(command_text):
        char = command_text[index]
        if quote is None:
            if command_text.startswith("$'", index):
                # shlex does not decode ANSI-C shell quotes; refusing the form
                # keeps every caller from classifying a different operand.
                raise ValueError("unsupported ANSI-C shell quote")
            in_pattern = bool(
                parenthesis_frames and parenthesis_frames[-1] == "pattern"
            )
            in_parameter = bool(
                parenthesis_frames and parenthesis_frames[-1] == "parameter"
            )
            if char == "#" and at_word_start and not in_pattern and not in_parameter:
                finish_word()
                end = command_text.find("\n", index)
                if comment_ranges is not None:
                    comment_ranges.append(
                        (index, end if end >= 0 else len(command_text))
                    )
                if end < 0:
                    break
                index = end
                continue
            if command_text.startswith("$(", index):
                finish_word()
                protected.extend("$(")
                parenthesis_frames.append("substitution")
                word_start, at_word_start, index = len(protected), True, index + 2
                continue
            if command_text.startswith("${", index):
                protected.extend("${")
                parenthesis_frames.append("parameter")
                at_word_start, index = False, index + 2
                continue
            if char == "}" and in_parameter:
                protected.append(char)
                parenthesis_frames.pop()
                at_word_start, index = False, index + 1
                continue
            if in_parameter and char in shell_punctuation | {" ", "\t", "\r"}:
                protected.append(protected_punctuation.get(char, char))
                at_word_start, index = False, index + 1
                continue
            if char == "\\" and index + 1 < len(command_text):
                following = command_text[index + 1]
                if following == "\n":
                    index += 2
                    continue
                protected.append(
                    protected_punctuation.get(following, char + following)
                    if following in shell_punctuation
                    else char + following
                )
                word_quoted, at_word_start, index = True, False, index + 2
                continue
            if char in {chr(39), chr(34)}:
                quote, word_quoted = char, True
            elif char in "?*+@!" and command_text[index : index + 2] == char + "(":
                protected.extend((char, protected_punctuation["("]))
                parenthesis_frames.append("pattern")
                at_word_start, index = False, index + 2
                continue
            elif char == "(" and in_pattern:
                parenthesis_frames.append("pattern")
            elif (
                char == "\r"
                and parenthesis_frames
                and parenthesis_frames[-1] == "assignment"
            ):
                protected.append(protected_punctuation[char])
                at_word_start, index = False, index + 1
                continue
            elif char in " \t\n;&|<>()" and not in_pattern:
                assignment = char == "(" and re.fullmatch(
                    r"[A-Za-z_][A-Za-z0-9_]*\+?=", "".join(protected[word_start:])
                )
                finish_word()
                if char == "(":
                    parenthesis_frames.append(
                        "assignment"
                        if assignment
                        else "process"
                        if protected and protected[-1] in "<>"
                        else "group"
                    )
                assignment_delimiter = (
                    bool(assignment)
                    or char == ")"
                    and parenthesis_frames
                    and parenthesis_frames[-1] == "assignment"
                )
                array_whitespace = (
                    char in " \t\r\n"
                    and parenthesis_frames
                    and parenthesis_frames[-1] == "assignment"
                )
                protected.append(
                    protected_punctuation[char]
                    if assignment_delimiter or array_whitespace
                    else char
                )
                word_start, at_word_start = len(protected), True
                if char == ")" and parenthesis_frames:
                    frame = parenthesis_frames.pop()
                    at_word_start = frame == "group"
                    if frame == "substitution-double":
                        quote = chr(34)
                index += 1
                continue
            protected.append(
                protected_punctuation.get(char, char) if in_pattern else char
            )
            at_word_start = False
            if char == ")" and in_pattern:
                parenthesis_frames.pop()
        elif (
            scan_substitutions
            and quote == chr(34)
            and command_text.startswith("$(", index)
        ):
            protected.extend("$(")
            parenthesis_frames.append("substitution-double")
            quote, at_word_start, index = None, True, index + 2
            continue
        elif char == quote:
            protected.append(char)
            quote, at_word_start = None, False
        elif quote == chr(34) and char == "\\" and index + 1 < len(command_text):
            if command_text[index + 1] == "\n":
                index += 2
                continue
            protected.extend(command_text[index : index + 2])
            index += 1
        else:
            protected.append(
                protected_punctuation.get(char, char)
                if char in shell_punctuation
                else char
            )
        index += 1
    finish_word()
    return "".join(protected)


def decode_protected_punctuation(token):
    return "".join(
        unprotected_punctuation.get(char, char) for char in token.replace("\ue100", "")
    )


def substitution_spans(command_text: str) -> list[tuple[int, int, str]] | None:
    comments = []
    try:
        protect_quoted_punctuation(
            command_text, comment_ranges=comments, scan_substitutions=True
        )
    except ValueError:
        return None
    comment_ends = dict(comments)
    commands = []
    quote = None
    index = 0
    while index < len(command_text):
        if index in comment_ends:
            index = comment_ends[index]
            continue
        char = command_text[index]
        if char == "\\" and quote != chr(39):
            index += 2
            continue
        if char in {chr(39), chr(34)}:
            quote = None if quote == char else char if quote is None else quote
            index += 1
            continue
        if quote != chr(39) and char == "`":
            end = command_text.find("`", index + 1)
            if end < 0:
                return None
            commands.append((index, end + 1, command_text[index + 1 : end]))
            index = end + 1
            continue
        if quote != chr(39) and command_text.startswith("$(", index):
            depth = 1
            nested_quote = None
            end = index + 2
            while end < len(command_text) and depth:
                if end in comment_ends:
                    end = comment_ends[end]
                    continue
                nested_char = command_text[end]
                if nested_char == "\\" and nested_quote != chr(39):
                    end += 2
                    continue
                if nested_char in {chr(39), chr(34)}:
                    nested_quote = (
                        None
                        if nested_quote == nested_char
                        else nested_char
                        if nested_quote is None
                        else nested_quote
                    )
                elif nested_quote is None and nested_char == "(":
                    depth += 1
                elif nested_quote is None and nested_char == ")":
                    depth -= 1
                end += 1
            if depth:
                return None
            commands.append((index, end, command_text[index + 2 : end - 1]))
            index = end
            continue
        index += 1
    return commands


def substitution_commands(command_text: str) -> list[str] | None:
    spans = substitution_spans(command_text)
    return None if spans is None else [command for _, _, command in spans]


def command_contexts(command_text: str) -> list[tuple[str, list[str], str]] | None:
    """Keep substitutions attached to their original outer command context."""
    spans = substitution_spans(command_text)
    if spans is None:
        return None
    comments = []
    protect_quoted_punctuation(
        command_text, comment_ranges=comments, scan_substitutions=True
    )
    comment_ends = dict(comments)
    by_start = {start: (end, command) for start, end, command in spans}
    marker = "__codex_substitution__"
    collision_text = command_text.replace("\\\n", "").translate(
        str.maketrans("", "", "'\"\\")
    )
    while marker in collision_text:
        marker += "_"
    contexts, parts, nested = [], [], []
    parenthesis_frames, word_start = [], 0
    quote = None
    index = 0
    while index < len(command_text):
        if index in comment_ends:
            index = comment_ends[index]
            continue
        if index in by_start:
            end, command = by_start[index]
            parts.append(marker)
            nested.append(command)
            index = end
            continue
        char = command_text[index]
        if char == "\\" and quote != chr(39):
            if command_text[index : index + 2] == "\\\n":
                index += 2
                continue
            parts.append(command_text[index : index + 2])
            index += 2
            continue
        if char in {chr(39), chr(34)}:
            quote = None if quote == char else char if quote is None else quote
        if quote is None and command_text[index : index + 2] in {
            ">&",
            "<&",
            "&>",
            ">|",
        }:
            parts.append(command_text[index : index + 2])
            index += 2
            continue
        in_pattern = bool(parenthesis_frames and parenthesis_frames[-1][0] == "pattern")
        in_parameter = bool(
            parenthesis_frames and parenthesis_frames[-1][0] == "parameter"
        )
        if quote is None and command_text.startswith("${", index):
            parenthesis_frames.append(("parameter", word_start))
            parts.append("${")
            index += 2
            continue
        if quote is None and char == "}" and in_parameter:
            parenthesis_frames.pop()
            parts.append(char)
            index += 1
            continue
        if in_parameter:
            parts.append(char)
            index += 1
            continue
        if (
            quote is None
            and char in "?*+@!"
            and command_text[index : index + 2] == char + "("
        ):
            parenthesis_frames.append(("pattern", word_start))
            parts.extend((char, "("))
            index += 2
            continue
        following = index + 1
        while command_text[following : following + 2] == "\\\n":
            following += 2
        brace_boundary = (
            char in "{}"
            and not parenthesis_frames
            and word_start == len(parts)
            and (
                following == len(command_text)
                or command_text[following] in " \t\n;&|(){}"
            )
        )
        assignment_delimiter = False
        if quote is None and char == "(" and in_pattern:
            parenthesis_frames.append(("pattern", word_start))
            assignment_delimiter = True
        elif (
            quote is None
            and char == "("
            and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\+?=", "".join(parts[word_start:]))
        ):
            parenthesis_frames.append(("assignment", word_start))
            assignment_delimiter = True
        elif quote is None and char == ")" and parenthesis_frames:
            _, word_start = parenthesis_frames.pop()
            assignment_delimiter = True
        if (
            quote is None
            and not in_pattern
            and not assignment_delimiter
            and not (char == "\n" and parenthesis_frames)
            and (char in ";&|()\n" or brace_boundary)
        ):
            if parts:
                contexts.append(("".join(parts), nested, marker))
                parts, nested = [], []
            word_start = 0
        else:
            parts.append(char)
            if quote is None and (
                char in " \t\n" or assignment_delimiter and char == "("
            ):
                word_start = len(parts)
        index += 1
    if parts:
        contexts.append(("".join(parts), nested, marker))
    return contexts


def reconciliation_thread(tokens: list[str]) -> str:
    """Return the sole bound thread, or reject unsupported request grammar."""
    if (
        len(tokens) < 3
        or tokens[0].rsplit("/", 1)[-1] != "gh"
        or tokens[1:3] != ["api", "graphql"]
    ):
        return ""
    fields: dict[str, str] = {}
    tail = iter(tokens[3:])
    for option in tail:
        if option not in {"-f", "--raw-field"}:
            return ""
        field = next(tail, "")
        key, separator, value = field.partition("=")
        if not separator or key in fields or key not in {"query", "threadId", "body"}:
            return ""
        if "$(" in value or "`" in value:
            return ""
        fields[key] = value
    thread = fields.get("threadId", "")
    if not re.fullmatch(r"PRRT_[A-Za-z0-9_-]+", thread):
        return ""
    query = re.sub(r"\s+", "", fields.get("query", ""))
    resolve = "mutation($threadId:ID!){resolveReviewThread(input:{threadId:$threadId}){thread{id}}}"
    reply = "mutation($threadId:ID!,$body:String!){addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$threadId,body:$body}){comment{id}}}"
    contracts = {resolve: {"query", "threadId"}, reply: {"query", "threadId", "body"}}
    return (
        thread
        if set(fields) == contracts.get(query)
        and ("body" not in fields or fields["body"])
        else ""
    )


if __name__ == "__main__":
    try:
        thread = reconciliation_thread(shlex.split(sys.argv[1]))
    except (ValueError, IndexError):
        thread = ""
    if thread:
        print(thread)
    raise SystemExit(0 if thread else 1)
