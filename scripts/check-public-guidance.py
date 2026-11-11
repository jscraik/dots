"""Check the public instruction provenance, scopes and local CommonMark pointers."""

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
REVISION = "cfd2e591c1e9439363955ffa93b6f396afc7a4ad"
MARKDOWN = MarkdownIt("commonmark")


def anchors(text: str) -> set[str]:
    counts: dict[str, int] = {}
    result = set()
    tokens = MARKDOWN.parse(text)
    for index, token in enumerate(tokens):
        if token.type != "heading_open":
            continue
        title = tokens[index + 1].content
        title = re.sub(r"<[^>]+>", "", title).lower()
        slug = re.sub(r"[^\w\- ]", "", title).replace(" ", "-")
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        result.add(slug + (f"-{count}" if count else ""))
    return result


def check_tree(root: Path) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    provenance = json.loads(
        (root / "codex/templates/guidance-provenance.json").read_text()
    )
    if (
        provenance.get("schema_version") != 1
        or provenance.get("source_revision") != REVISION
    ):
        errors.append("Guidance provenance revision or schema changed")
    for row in provenance["files"]:
        path = root / row["path"]
        if (
            path.is_symlink()
            or not path.resolve().is_relative_to(root)
            or not path.is_file()
        ):
            errors.append("Missing or outside public source: " + row["path"])
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != row.get("candidate_sha256"):
            errors.append("Guidance provenance drift: " + row["path"])
    documents = [
        root / "AGENTS.md",
        root / "codex/AGENTS.md",
        *sorted((root / "codex/instructions").rglob("*.md")),
    ]
    for path in documents:
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            errors.append("Guidance must be a canonical local file")
            continue
        text = path.read_text()
        if re.search(r"/Users/[^/\s]+|JSC-\d+", text):
            errors.append(
                "Private path or operational identifier: "
                + path.relative_to(root).as_posix()
            )
        for token in MARKDOWN.parse(text):
            for child in token.children or []:
                if child.type not in {"link_open", "image"}:
                    continue
                href = child.attrGet("href" if child.type == "link_open" else "src")
                parsed = urlsplit(href or "")
                if parsed.scheme or parsed.netloc:
                    continue
                target = (
                    (path.parent / unquote(parsed.path)).resolve()
                    if parsed.path
                    else path
                )
                if not target.is_relative_to(root) or not target.is_file():
                    errors.append(
                        f"{path.relative_to(root)}: missing local Context Pointer {href}"
                    )
                elif parsed.fragment and unquote(parsed.fragment) not in anchors(
                    target.read_text()
                ):
                    errors.append(f"{path.relative_to(root)}: missing heading {href}")
    baseline = (root / "codex/AGENTS.md").read_text()
    for required in (
        "Permission availability is capability, not task authorization",
        "Preserve hooks and permissions",
        "stale-head, unauthenticated, failed or missing",
        "current-head receipt",
        "runtime databases",
        "outgoing owner",
        "instructions/agents/16-git-and-release.md",
    ):
        if required not in baseline:
            errors.append("Portable baseline lost a safeguard: " + required)
    release = (root / "codex/instructions/agents/16-git-and-release.md").read_text()
    for required in (
        "current full head",
        "write-receipt",
        "full review",
        "informational",
        "quorum",
    ):
        if required not in release:
            errors.append("Release contract lost a safeguard: " + required)
    for name in ("USER_PROFILE.md", "USER_PROFILE.detail.md"):
        text = (root / "codex/instructions" / name).read_text()
        if "local-context/USER_PROFILE.md" not in text or "display_name:" in text:
            errors.append("User context must remain a public local-only pointer")
    return errors


if __name__ == "__main__":
    failures = check_tree(ROOT)
    if failures:
        print("\n".join(failures))
        raise SystemExit(1)
    print(
        "PASS: public instruction provenance, scope safeguards and local Context Pointers"
    )
