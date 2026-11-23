"""Refresh one PR description through the receipt-bound body-only path."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path


def _fixture_scope():
    import importlib.util
    from pathlib import Path

    directory = Path(__file__).resolve().parent
    if directory.name == "hook-governance":
        directory = directory.parent
    spec = importlib.util.spec_from_file_location(
        "dots_helper_scope", directory / "helper_fixture_scope.py"
    )
    scope = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scope)
    return scope


def _fixture_args(arguments):
    return _fixture_scope().admit_file(__file__, arguments)


def _fixture_resource(value):
    return _fixture_scope().resource(value)


def _fixture_text(text):
    from pathlib import Path

    directory = Path(__file__).resolve().parent
    if directory.name == "hook-governance":
        directory = directory.parent
    policy = directory.parent
    return (
        text.replace("@POLICY_SOURCE@", str(policy))
        .replace("@REPO@", str(policy.parent))
        .replace("@HOME@", str(Path.home()))
    )


def _fixture_open(*args, **kwargs):
    return _fixture_scope().fixture_open(*args, **kwargs)


SERVICE = "pr-body-refresh"
SCHEMA_VERSION = "pr-body-refresh/v1"
CONDITIONAL_FIELDS_MARKER = (
    "Complete the following fields only when their admission conditions apply."
)


class RefreshBlocked(RuntimeError):
    """Raised when a proposed description update does not meet its contract."""


def parse_pr_number(value: str) -> int:
    """Parse a positive pull-request number without accepting shell syntax."""
    if not value.isdecimal():
        raise ValueError("--pr must be a positive decimal pull-request number")
    number = int(value)
    if number < 1:
        raise ValueError("--pr must be a positive decimal pull-request number")
    return number


def parse_repo_slug(value: str) -> str:
    """Accept exactly one GitHub owner/name repository slug."""
    parts = value.split("/")
    if len(parts) != 2 or any(not part for part in parts):
        raise ValueError("--repo must use the owner/name form")
    if any(
        any(not (character.isalnum() or character in "-_.") for character in part)
        for part in parts
    ):
        raise ValueError("--repo may contain only owner/name characters")
    return value


def required_template_sections(template_path: Path) -> list[str]:
    """Return the top-level sections the configured PR template requires."""
    sections = [
        section
        for section, _label, _value in _field_entries(
            template_path, "PR template", include_sections_without_fields=True
        )
        if section
    ]
    sections = list(dict.fromkeys(sections))
    if not sections:
        raise RefreshBlocked(f"PR template has no top-level sections: {template_path}")
    return sections


def _non_comment_lines(path: Path, unavailable_label: str) -> list[str]:
    """Read Markdown lines while excluding HTML-comment-only template guidance."""
    try:
        lines = _fixture_resource(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RefreshBlocked(
            f"{unavailable_label} is unavailable: {path}: {exc}"
        ) from exc
    visible: list[str] = []
    comment_open = False
    fence_marker: str | None = None
    for line in lines:
        stripped = line.strip()
        if "<!--" in stripped:
            comment_open = "-->" not in stripped[stripped.find("<!--") + 4 :]
            continue
        if comment_open:
            if "-->" in stripped:
                comment_open = False
            continue
        if fence_marker is not None:
            if stripped.startswith(fence_marker):
                fence_marker = None
            continue
        if stripped.startswith(("```", "~~~")):
            fence_marker = stripped[:3]
            continue
        visible.append(line)
    return visible


def _field_key(label: str) -> str:
    """Normalize the template's checkbox marker before comparing field labels."""
    normalized = label.strip()
    if normalized.startswith("[") and "]" in normalized:
        normalized = normalized.split("]", 1)[1].strip()
    return normalized


def _field_entries(
    path: Path, unavailable_label: str, *, include_sections_without_fields: bool = False
) -> list[tuple[str, str, str]]:
    """Return visible ``(section, label, value)`` entries in Markdown order."""
    entries: list[tuple[str, str, str]] = []
    current_section: str | None = None
    seen_sections: list[str] = []
    for line in _non_comment_lines(path, unavailable_label):
        stripped = line.strip()
        if stripped.startswith("## ") and stripped[3:].strip():
            current_section = stripped[3:].strip()
            if current_section not in seen_sections:
                seen_sections.append(current_section)
            continue
        if (
            current_section is None
            or not stripped.startswith("- ")
            or ":" not in stripped
        ):
            continue
        label, _separator, value = stripped[2:].partition(":")
        key = _field_key(label)
        if key:
            entries.append((current_section, key, value.strip()))
    if include_sections_without_fields:
        return [(section, "", "") for section in seen_sections] + entries
    return entries


def _section_lines(path: Path, unavailable_label: str) -> dict[str, list[str]]:
    """Return visible Markdown lines grouped by their nearest ``##`` heading."""
    sections: dict[str, list[str]] = {}
    current_section: str | None = None
    for line in _non_comment_lines(path, unavailable_label):
        stripped = line.strip()
        if stripped.startswith("## ") and stripped[3:].strip():
            current_section = stripped[3:].strip()
            sections.setdefault(current_section, [])
            continue
        if current_section is not None:
            sections[current_section].append(line)
    return sections


def _conditional_template_fields(template_path: Path) -> set[tuple[str, str]]:
    """Return template fields below the conditional-evidence guidance marker."""
    try:
        lines = (
            _fixture_resource(template_path).read_text(encoding="utf-8").splitlines()
        )
    except OSError as exc:
        raise RefreshBlocked(
            f"PR template is unavailable: {template_path}: {exc}"
        ) from exc
    current_section: str | None = None
    conditional = False
    fence_marker: str | None = None
    fields: set[tuple[str, str]] = set()
    for line in lines:
        stripped = line.strip()
        if fence_marker is not None:
            if stripped.startswith(fence_marker):
                fence_marker = None
            continue
        if stripped.startswith(("```", "~~~")):
            fence_marker = stripped[:3]
            continue
        if stripped.startswith("## ") and stripped[3:].strip():
            current_section = stripped[3:].strip()
            conditional = False
            continue
        if CONDITIONAL_FIELDS_MARKER in stripped:
            conditional = True
            continue
        if not conditional or current_section is None:
            continue
        if stripped.startswith("- ") and ":" in stripped:
            label, _separator, _value = stripped[2:].partition(":")
            key = _field_key(label)
            if key:
                fields.add((current_section, key))
    return fields


def required_template_fields(template_path: Path) -> list[str]:
    """Return required Markdown bullet labels from the active PR template."""
    fields: list[str] = []
    for _section, label, _value in _field_entries(template_path, "PR template"):
        if label and label not in fields:
            fields.append(label)
    return fields


def body_sections(body_path: Path) -> set[str]:
    """Return the top-level sections supplied by a candidate PR body file."""
    return {
        section
        for section, _label, _value in _field_entries(
            body_path, "PR body file", include_sections_without_fields=True
        )
        if section
    }


def missing_template_sections(template_path: Path, body_path: Path) -> list[str]:
    """Identify template sections absent from the body without interpreting prose."""
    present = body_sections(body_path)
    return [
        section
        for section in required_template_sections(template_path)
        if section not in present
    ]


def missing_template_fields(template_path: Path, body_path: Path) -> list[str]:
    """Identify empty or missing field labels without interpreting prose values."""
    template_entries = _field_entries(template_path, "PR template")
    supplied: dict[tuple[str, str], list[str]] = {}
    for section, label, value in _field_entries(body_path, "PR body file"):
        supplied.setdefault((section, label), []).append(value)
    label_counts = Counter((label for _section, label, _value in template_entries))
    conditional_fields = _conditional_template_fields(template_path)
    occurrences: Counter[tuple[str, str]] = Counter()
    missing: list[str] = []
    for section, label, template_value in template_entries:
        key = (section, label)
        occurrence = occurrences[key]
        occurrences[key] += 1
        values = supplied.get(key, [])
        value = values[occurrence] if occurrence < len(values) else ""
        if not value and key in conditional_fields:
            continue
        checklist_field = section.casefold() == "checklist"
        if not value or (
            not checklist_field and _is_template_placeholder(value, template_value)
        ):
            missing.append(label if label_counts[label] == 1 else f"{section}: {label}")
    return missing


def _normalize_field_value(value: str) -> str:
    """Normalize whitespace before comparing a body value with a template placeholder."""
    return re.sub("\\s+", " ", value).strip()


def _is_template_placeholder(value: str, template_value: str) -> bool:
    """Return whether a body value is still the literal value from the template."""
    normalized_value = _normalize_field_value(value)
    normalized_template = _normalize_field_value(template_value)
    return bool(normalized_template) and normalized_value == normalized_template


COMMAND_EVIDENCE_PATTERN = re.compile(
    "^-\\s*Command:\\s*(?P<command>`[^\\n`]+`|(?=\\S).*?\\S)\\s*->\\s*(?P<status>`?(?:pass|fail|not run|n\\.a\\.|n/a|blocked)`?)(?P<reason>.*)$",
    re.IGNORECASE,
)
COMMAND_PLACEHOLDER_PATTERN = re.compile("^(?:<[^>\\n]+>|\\.\\.\\.)$")


def _balanced_reason(value: str, *, required: bool) -> bool:
    """Validate one optional or required parenthesized outcome reason."""
    reason = value.strip()
    if not reason:
        return not required
    if reason.endswith(".") and reason[:-1].rstrip().endswith(")"):
        reason = reason[:-1].rstrip()
    if not (reason.startswith("(") and reason.endswith(")")):
        return False
    depth = 0
    for character in reason:
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _valid_command_evidence(line: str) -> bool:
    """Validate command evidence without retaining or echoing its contents."""
    match = COMMAND_EVIDENCE_PATTERN.fullmatch(line)
    if match is None:
        return False
    command = match.group("command").strip()
    if command.startswith("`") and command.endswith("`"):
        command = command[1:-1].strip()
    if COMMAND_PLACEHOLDER_PATTERN.fullmatch(command):
        return False
    status = match.group("status").strip("`").lower()
    return _balanced_reason(
        match.group("reason"), required=status in {"blocked", "not run", "n.a.", "n/a"}
    )


def validation_command_errors(template_path: Path, body_path: Path) -> list[str]:
    """Validate command evidence when the active template defines a proof section."""
    required_sections = required_template_sections(template_path)
    evidence_section = next(
        (
            section
            for section in ("Testing", "Validation")
            if section in required_sections
        ),
        None,
    )
    if evidence_section is None and {"Evidence", "Impact and risk", "Readiness"} <= set(required_sections):
        evidence_section = "Evidence"
    if evidence_section is None:
        return []
    validation_lines = [
        line.strip()
        for line in _section_lines(body_path, "PR body file").get(evidence_section, [])
    ]
    command_lines = [
        line for line in validation_lines if line.lower().startswith("- command:")
    ]
    if not command_lines:
        return [
            f"{evidence_section} section must include at least one Command evidence line."
        ]
    return [
        f"Command evidence has invalid format at {evidence_section.lower()} line {line_number}."
        for line_number, line in enumerate(command_lines, start=1)
        if not _valid_command_evidence(line)
    ]


def build_edit_command(pr_number: int, repo_slug: str, body_path: Path) -> list[str]:
    """Build the sole hosted mutation permitted by this helper."""
    return [
        "gh",
        "pr",
        "edit",
        str(pr_number),
        "--repo",
        repo_slug,
        "--body-file",
        str(body_path),
    ]


def run_command(command: list[str], root: Path) -> subprocess.CompletedProcess[str]:
    """Run one fixed command without a shell and capture only diagnostic output."""
    return subprocess.run(
        command, cwd=root, text=True, capture_output=True, check=False
    )


def receipt_for_current_pr(root: Path) -> dict[str, object]:
    """Consume the projected update receipt and return its validated payload."""
    readiness_script = Path(__file__).resolve().with_name("pr-readiness.py")
    if not readiness_script.is_file():
        raise RefreshBlocked(
            f"projected PR-readiness script is missing: {readiness_script}"
        )
    result = run_command(
        [
            sys.executable,
            str(readiness_script),
            "--phase",
            "update",
            "--repo-root",
            str(root),
            "--check-receipt",
            "--json",
        ],
        root,
    )
    if result.returncode != 0:
        raise RefreshBlocked(
            "the current update-phase PR-readiness receipt does not pass"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RefreshBlocked("the PR-readiness receipt did not return JSON") from exc
    if not isinstance(payload, dict) or payload.get("status") != "pass":
        raise RefreshBlocked(
            "the current update-phase PR-readiness receipt is not passing"
        )
    return payload


def repair_preflight_for_current_pr(root: Path, pr_number: int) -> dict[str, object]:
    """Bind a body-only repair to the checkout and current hosted PR head.

    A newly-created PR can fail its metadata checks before an update-phase
    readiness receipt can exist. This narrower preflight admits only a
    template-complete body repair; it does not assert review, checks, or merge
    readiness and cannot be used for any other PR mutation.
    """
    head_result = run_command(
        [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--json",
            "number,headRefOid,state,isDraft",
        ],
        root,
    )
    if head_result.returncode != 0:
        raise RefreshBlocked("the current pull-request head could not be read")
    try:
        payload = json.loads(head_result.stdout)
    except json.JSONDecodeError as exc:
        raise RefreshBlocked("the pull-request head response was not JSON") from exc
    if not isinstance(payload, dict) or payload.get("number") != pr_number:
        raise RefreshBlocked("the pull-request head response did not match --pr")
    if str(payload.get("state", "")).upper() != "OPEN":
        raise RefreshBlocked("metadata repair requires an open pull request")
    remote_head = payload.get("headRefOid")
    if not isinstance(remote_head, str) or not remote_head:
        raise RefreshBlocked("the pull-request head response has no commit SHA")
    local_result = run_command(["git", "rev-parse", "HEAD"], root)
    if local_result.returncode != 0 or local_result.stdout.strip() != remote_head:
        raise RefreshBlocked(
            "metadata repair requires local HEAD to match the hosted PR head"
        )
    return {"mode": "metadata_repair", "pr": pr_number, "head_sha": remote_head}


def receipt_pr_number(payload: dict[str, object]) -> int:
    """Extract the current hosted PR number from a passing receipt payload."""
    lanes = payload.get("lanes")
    if not isinstance(lanes, dict):
        raise RefreshBlocked("the PR-readiness receipt has no pull-request lane")
    pull_request = lanes.get("pull_request")
    if not isinstance(pull_request, dict):
        raise RefreshBlocked("the PR-readiness receipt has no pull-request details")
    details = pull_request.get("details")
    number = details.get("number") if isinstance(details, dict) else None
    if not isinstance(number, int) or number < 1:
        raise RefreshBlocked(
            "the PR-readiness receipt has no current pull-request number"
        )
    return number


def current_repository_slug(root: Path) -> str:
    """Read the repository identity before applying the requested destination."""
    result = run_command(["gh", "repo", "view", "--json", "nameWithOwner"], root)
    if result.returncode != 0:
        raise RefreshBlocked("the current repository identity could not be read")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RefreshBlocked("the current repository identity was not JSON") from exc
    slug = payload.get("nameWithOwner") if isinstance(payload, dict) else None
    if not isinstance(slug, str):
        raise RefreshBlocked(
            "the current repository identity did not include nameWithOwner"
        )
    return parse_repo_slug(slug)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the deliberately narrow helper interface."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", required=True, type=parse_pr_number)
    parser.add_argument("--repo", required=True, type=parse_repo_slug)
    parser.add_argument("--body-file", required=True, type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--repair",
        action="store_true",
        help="allow only a current-head metadata repair when checks block update receipt creation",
    )
    return _fixture_args(parser.parse_args(argv))


def _execute_snapshot(args: argparse.Namespace) -> dict[str, object]:
    """Validate fixed inputs, then perform only the approved body-file update."""
    root = args.repo_root.expanduser().resolve()
    template_path = root / ".github" / "PULL_REQUEST_TEMPLATE.md"
    body_path = args.body_file.expanduser().resolve()
    if not body_path.is_file():
        raise RefreshBlocked(f"--body-file must name a regular file: {body_path}")
    template_sections: list[str] = []
    if not template_path.exists():
        if not args.repair:
            raise RefreshBlocked(
                "PR template absence is supported only for explicit metadata repair"
            )
        inventory = run_command(
            ["git", "ls-tree", "--full-tree", "-r", "--name-only", "-z", "HEAD"], root
        )
        if inventory.returncode != 0 or not inventory.stdout.endswith("\x00"):
            raise RefreshBlocked("PR template absence could not be verified from HEAD")
        for name in inventory.stdout.split("\x00"):
            parts = name.lower().split("/")
            if any(
                part == "pull_request_template"
                or part.startswith("pull_request_template.")
                for part in parts
            ):
                raise RefreshBlocked(
                    "PR template exists in HEAD; restore or select the repository template"
                )
        try:
            body_text = _fixture_resource(body_path).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise RefreshBlocked("PR body file is not readable UTF-8") from exc
        if not body_text.strip():
            raise RefreshBlocked("PR body must not be empty")
    else:
        template_sections = required_template_sections(template_path)
        missing_sections = missing_template_sections(template_path, body_path)
        if missing_sections:
            raise RefreshBlocked(
                "PR body omits template sections: " + ", ".join(missing_sections)
            )
        missing_fields = missing_template_fields(template_path, body_path)
        if missing_fields:
            raise RefreshBlocked(
                "PR body omits required template values: " + ", ".join(missing_fields)
            )
        command_errors = validation_command_errors(template_path, body_path)
        if command_errors:
            raise RefreshBlocked("; ".join(command_errors))
    if args.repair:
        receipt = repair_preflight_for_current_pr(root, args.pr)
    else:
        receipt = receipt_for_current_pr(root)
        if receipt_pr_number(receipt) != args.pr:
            raise RefreshBlocked(
                "--pr does not match the current receipt-bound pull request"
            )
    if current_repository_slug(root) != args.repo:
        raise RefreshBlocked("--repo does not match the current repository")
    command = build_edit_command(args.pr, args.repo, body_path)
    if args.dry_run:
        return {
            "schema_version": SCHEMA_VERSION,
            "service": SERVICE,
            "status": "pass",
            "action": "dry_run",
            "pr": args.pr,
            "repo": args.repo,
            "mode": receipt.get("mode", "receipt_bound"),
            "template_sections": template_sections,
        }
    result = run_command(command, root)
    if result.returncode != 0:
        raise RefreshBlocked("gh pr edit --body-file did not complete")
    return {
        "schema_version": SCHEMA_VERSION,
        "service": SERVICE,
        "status": "pass",
        "action": "updated",
        "pr": args.pr,
        "repo": args.repo,
        "mode": receipt.get("mode", "receipt_bound"),
        "template_sections": template_sections,
    }


def execute(args: argparse.Namespace) -> dict[str, object]:
    """Validate and upload the same private copy of a regular, non-symlink body."""
    supplied = args.body_file.expanduser()
    if ".." in supplied.parts:
        raise RefreshBlocked("PR body path must not contain parent-directory traversal")
    source = supplied.absolute()
    try:
        directory = _fixture_resource(os).open(
            source.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        )
        try:
            for component in source.parts[1:-1]:
                child = _fixture_resource(os).open(
                    component,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=directory,
                )
                os.close(directory)
                directory = child
            descriptor = _fixture_resource(os).open(
                source.name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=directory,
            )
        finally:
            os.close(directory)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise RefreshBlocked("--body-file must name a regular non-symlink file")
            content = stream.read()
        content.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise RefreshBlocked(
            "PR body file must be readable UTF-8 and not a symlink"
        ) from exc
    with tempfile.TemporaryDirectory(prefix="pr-body-validated-") as directory:
        snapshot = Path(directory) / "body.md"
        _fixture_scope().output(snapshot).write_bytes(content)
        _fixture_scope().output(snapshot).chmod(384)
        copied = argparse.Namespace(**vars(args))
        copied.body_file = snapshot
        return _execute_snapshot(copied)


def main(argv: list[str] | None = None) -> int:
    """Emit structured proof while withholding body contents and command output."""
    args = parse_args(argv)
    try:
        print(json.dumps(execute(args), sort_keys=True))
    except RefreshBlocked as exc:
        print(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "service": SERVICE,
                    "status": "blocked",
                    "error": str(exc),
                },
                sort_keys=True,
            )
        )
        return 2
    return 0


if __name__ == "__main__":
    _fixture_scope().admit_file(__file__)
    raise SystemExit(main())
