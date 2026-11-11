"""Validate codestyle-routing enforcement across active docs and hooks."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt


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


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_ROOT = SCRIPT_DIR.parent


@dataclass(frozen=True)
class ContainsCheck:
    path: str
    needles: tuple[str, ...]


DOC_CHECKS = (
    ContainsCheck("AGENTS.md", ("instructions/CODESTYLE.md",)),
    ContainsCheck("instructions/README.md", ("[CODESTYLE.md](./CODESTYLE.md)",)),
    ContainsCheck(
        "instructions/README.md",
        ("active repository's", "Discover skills", "checkout-relative"),
    ),
    ContainsCheck(
        "../AGENTS.md",
        (
            "codex/instructions/README.md#start-here",
            "$config-drift-guard",
            "$validation-contract-check",
            "$mcp-startup-triage",
            "$ci-check-name-parity",
            "codex/scripts/verify-work.sh --fast",
            ".harness/memory/LEARNINGS.md",
            "codex/FORJAMIE.md",
        ),
    ),
    ContainsCheck(
        "instructions/agents/01-instruction-map.md",
        ("[../CODESTYLE.md](../CODESTYLE.md)",),
    ),
)
HOOK_CHECKS = (
    ContainsCheck(
        "hooks/hook-runtime-lib.sh",
        ("skip codestyle", "instructions/CODESTYLE.md first"),
    ),
    ContainsCheck(
        "hooks/session-start.sh", ("CODESTYLE.md before deeper instruction modules",)
    ),
    ContainsCheck(
        "scripts/validate-codex-hooks.sh",
        ("user_codestyle_block_output", "instructions/CODESTYLE.md"),
    ),
)


def check_contains(root: Path, check: ContainsCheck) -> list[str]:
    """
    Verify that a file exists under the given root and contains the required substrings.

    Parameters:
        root (Path): Base directory against which `check.path` is resolved.
        check (ContainsCheck): Contains `path` (relative file path) and `needles` (tuple of substrings that must appear in the file).

    Returns:
        list[str]: A list of error messages. If the target file is missing the list contains a single
        item `"missing file: {path}"`. For an existing file, each missing required substring yields
        an item `"{path}: missing required text: '{needle}'"`. An empty list indicates no errors.
    """
    errors: list[str] = []
    target = root / check.path
    if not target.is_file():
        return [f"missing file: {check.path}"]
    text = _fixture_resource(target).read_text(encoding="utf-8")
    for needle in check.needles:
        if needle not in text:
            errors.append(f"{check.path}: missing required text: {needle!r}")
    return errors


def resolve_instruction_root(root: Path) -> Path:
    """Prefer the Codex subtree when the validator receives the repository root."""
    codex_root = root / "codex"
    if (codex_root / "AGENTS.md").is_file() and (codex_root / "hooks").is_dir():
        return codex_root
    return root


def active_link_destinations(text: str) -> list[str]:
    """Return active CommonMark link destinations, excluding code and comments."""
    return [
        str(child.attrGet("href"))
        for token in MarkdownIt("commonmark").parse(text)
        if token.type == "inline"
        for child in token.children or []
        if child.type == "link_open" and child.attrGet("href") is not None
    ]


def has_active_delivery_link(text: str) -> bool:
    """Recognize parsed CommonMark links, not comment or code contents."""
    destinations = {
        "instructions/agents/16-git-and-release.md",
        "./instructions/agents/16-git-and-release.md",
    }
    return bool(destinations.intersection(active_link_destinations(text)))


def has_active_governance_link(text: str) -> bool:
    """Accept equivalent checkout-relative links to the governance reference."""
    destinations = {
        "instructions/agents/07b-agent-governance.md",
        "./instructions/agents/07b-agent-governance.md",
    }
    return bool(destinations.intersection(active_link_destinations(text)))


def check_context_pointers(root: Path) -> list[str]:
    """Resolve front-door links through their canonical checkout, including projections."""
    front = root / "instructions/README.md"
    if not front.is_file():
        return ["missing instruction front door"]
    canonical = front.resolve()
    repository = root.resolve().parent
    if not canonical.is_relative_to(repository):
        return ["instruction front door escapes owning checkout"]
    failures: list[str] = []
    delivery = root / "instructions/agents/16-git-and-release.md"
    try:
        valid_delivery = (
            delivery.resolve().is_relative_to(repository) and delivery.is_file()
        )
    except (OSError, RuntimeError):
        valid_delivery = False
    if not valid_delivery:
        failures.append("missing or foreign Git delivery reference")
    agents_text = _fixture_resource(root / "AGENTS.md").read_text(encoding="utf-8")
    if not has_active_delivery_link(agents_text):
        failures.append("missing Git delivery link in AGENTS.md")
    governance = root / "instructions/agents/07b-agent-governance.md"
    try:
        valid_governance = (
            governance.resolve().is_relative_to(repository) and governance.is_file()
        )
    except (OSError, RuntimeError):
        valid_governance = False
    if not valid_governance:
        failures.append("missing or foreign agent governance reference")
    if not has_active_governance_link(agents_text):
        failures.append("missing agent governance link in AGENTS.md")
    if valid_delivery:
        review_parser = delivery.parent / "16a-review-reply-parsing.md"
        try:
            valid_parser = (
                review_parser.resolve().is_relative_to(repository)
                and review_parser.is_file()
            )
        except (OSError, RuntimeError):
            valid_parser = False
        if not valid_parser:
            failures.append("missing or foreign review-reply parsing reference")
        try:
            delivery_text = _fixture_resource(delivery).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            failures.append("unreadable Git delivery reference")
        else:
            if not {
                "./16a-review-reply-parsing.md",
                "16a-review-reply-parsing.md",
            }.intersection(active_link_destinations(delivery_text)):
                failures.append("missing review-reply parsing link in Git governance")
    content = _fixture_resource(canonical).read_text(encoding="utf-8")
    for link in active_link_destinations(content):
        parsed = urlsplit(link)
        if parsed.scheme or parsed.netloc or (not parsed.path):
            continue
        try:
            target = (canonical.parent / unquote(parsed.path)).resolve()
        except (OSError, RuntimeError, ValueError):
            failures.append(f"invalid instruction pointer target: {link}")
            continue
        if not target.is_relative_to(repository):
            failures.append(f"instruction pointer escapes owning checkout: {link}")
        elif not target.is_file():
            failures.append(f"missing instruction pointer target: {link}")
    for relative in (".codex/skills/README.md", "codex/instructions/CODESTYLE.md"):
        target = (repository / relative).resolve()
        if not target.is_relative_to(repository) or not target.is_file():
            failures.append(f"missing or foreign checkout route: {relative}")
    return failures


def main() -> int:
    """
    Run validation that codestyle instruction-routing is present across documentation files and hook scripts.

    Parses the optional `--root` argument, verifies the root directory exists, executes the checks defined by DOC_CHECKS and HOOK_CHECKS, and prints a short validation report to stdout.

    Returns:
        int: 0 when all checks pass; 1 if the root is missing or any check reports failures.
    """
    parser = argparse.ArgumentParser(
        description="Validate codestyle instruction-routing enforcement"
    )
    parser.add_argument(
        "--root",
        default=str(DEFAULT_ROOT),
        help="Repository root path (defaults to configs repo root)",
    )
    args = _fixture_args(parser.parse_args())
    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        print(f"[validate-instruction-routing] root not found: {root}")
        return 1
    instruction_root = resolve_instruction_root(root)
    if (instruction_root.parent / "harness.contract.json").is_file() and (
        not (instruction_root / "instructions/README.md")
        .resolve()
        .is_relative_to(instruction_root.parent)
    ):
        print(
            "[validate-instruction-routing] instruction front door escapes owning checkout"
        )
        return 1
    failures: list[str] = []
    if (instruction_root.parent / "harness.contract.json").is_file():
        for check in (*DOC_CHECKS, *HOOK_CHECKS):
            if (
                not (instruction_root / check.path)
                .resolve()
                .is_relative_to(instruction_root.parent)
            ):
                print(
                    f"[validate-instruction-routing] routing input escapes owning checkout: {check.path}"
                )
                return 1
    for check in DOC_CHECKS:
        if check.path == "../AGENTS.md" and (
            not (
                instruction_root.name == "codex"
                and (instruction_root.parent / "harness.contract.json").is_file()
            )
        ):
            continue
        failures.extend(check_contains(instruction_root, check))
    for check in HOOK_CHECKS:
        failures.extend(check_contains(instruction_root, check))
    if (instruction_root.parent / "harness.contract.json").is_file():
        failures.extend(check_context_pointers(instruction_root))
    global_guidance = (
        _fixture_resource(instruction_root / "AGENTS.md").read_text(encoding="utf-8")
        if (instruction_root / "AGENTS.md").is_file()
        else ""
    )
    for local_only in (
        "$config-drift-guard",
        "$validation-contract-check",
        "scripts/validate-codex-config.py",
        "codex/FORJAMIE.md",
        ".harness/memory/LEARNINGS.md",
        "## Discovery order",
    ):
        if local_only in global_guidance:
            failures.append(
                f"AGENTS.md: Configs-only guidance belongs in repository scope: {local_only}"
            )
    if failures:
        print("[validate-instruction-routing] validation failed:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("[validate-instruction-routing] OK: codestyle routing enforcement is present")
    return 0


if __name__ == "__main__":
    _fixture_scope().admit_file(__file__)
    raise SystemExit(main())
