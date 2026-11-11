"""Verify source-bound independent endorsements, never author dispositions.

Transport authentication belongs to the caller: entries must come from the
complete live GitHub review/comment inventory, not a caller-supplied file.
The endorsed tree permits commit-only changes without fresh endorsement.
"""
from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

MARKER = "pr-repair-endorsement/v1\n"
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ObjectId = Annotated[str, Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]
Nonempty = Annotated[str, Field(min_length=1, max_length=8192)]


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Source(StrictRecord):
    url: Nonempty
    sha256: Digest


class Proof(StrictRecord):
    source_url: Nonempty
    kind: Literal["regression", "inspection"]
    path: Nonempty
    blob_sha: ObjectId
    rationale: Nonempty


class Endorsement(StrictRecord):
    schema_version: Literal["pr-repair-endorsement/v1"]
    repository: Nonempty
    pr_number: Annotated[int, Field(gt=0)]
    reviewed_commit: ObjectId
    tree_sha: ObjectId
    coverage: Literal["complete current tree and all listed findings"]
    sources: Annotated[list[Source], Field(min_length=1, max_length=1000)]
    proofs: Annotated[list[Proof], Field(min_length=1, max_length=1000)]


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def parse_endorsement(body: str) -> Endorsement:
    if not body.startswith(MARKER) or len(body.encode()) > 131072:
        raise ValueError("missing endorsement marker or oversized endorsement")
    record = Endorsement.model_validate(json.loads(body[len(MARKER):], object_pairs_hook=_unique))
    urls = [source.url for source in record.sources]
    if len(set(urls)) != len(urls):
        raise ValueError("duplicate endorsed source")
    if {proof.source_url for proof in record.proofs} != set(urls):
        raise ValueError("each source requires its own proof")
    for proof in record.proofs:
        if not proof.rationale.strip() or any(part in {"", ".", ".."} for part in proof.path.split("/")):
            raise ValueError("invalid proof rationale or repository-relative path")
        if "\\" in proof.path or any(ord(char) < 32 for char in proof.path):
            raise ValueError("invalid proof path")
    return record


def completed_review(source: dict) -> bool:
    """Recognize completed review evidence, not an approval or clearance."""
    body = source.get("body")
    return (
        source.get("state") in ("APPROVED", "COMMENTED")
        and isinstance(body, str) and bool(body.strip())
        and not re.search(
            r"\b(?:quota\s+(?:exceeded|exhausted|limits?)|usage\s+limits?|rate[- ]limit(?:ed|s)?|"
            r"review\s+(?:failed|error)|unable\s+to\s+review|review\s+unavailable)\b",
            body, re.IGNORECASE,
        )
    )


def verify_endorsements(*, entries: list[dict], sources: list[dict], repository: str, pr_author: str,
                        number: int, head: str, reviewers: set[str], git: Callable[..., str],
                        review_sources: list[dict] | None = None,
                        required_review_count: int = 0,
                        ) -> tuple[list[dict], list[dict]]:
    """Return verified endorsements and source-specific gaps.

    `git` is the trusted caller's bounded Git reader. No candidate command,
    test, hook, or proof file is executed. Proof is an independently endorsed
    immutable artifact, not an inference from file existence or green tests.
    """
    expected = {source["url"]: source["sha256"] for source in sources}
    if not isinstance(pr_author, str) or not pr_author.strip():
        raise ValueError("authenticated PR author is required")
    pr_author = pr_author.casefold().removesuffix("[bot]")
    reviewers = {login.casefold().removesuffix("[bot]") for login in reviewers} - {pr_author}
    if type(required_review_count) is not int or required_review_count < 0:
        raise ValueError("invalid required review count")
    review_sources = review_sources or []
    accepted: list[dict] = []
    gaps: list[dict] = []
    for entry in entries:
        body = entry.get("body") or ""
        if not isinstance(body, str) or not body.startswith(MARKER):
            continue
        url = entry.get("html_url", "")
        author = (entry.get("user") or {}).get("login", "").casefold().removesuffix("[bot]")
        if author not in reviewers:
            gaps.append({"source": url, "reason": "endorsement is not from an independent reviewer"})
            continue
        try:
            record = parse_endorsement(body)
            if record.repository != repository or record.pr_number != number:
                raise ValueError("endorsement repository or PR mismatch")
            if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", head):
                raise ValueError("invalid current head")
            if git("rev-parse", f"{head}^{{tree}}") != record.tree_sha:
                raise ValueError("current tree is outside existing endorsement coverage")
            if git("cat-file", "-t", record.reviewed_commit) != "commit":
                raise ValueError("reviewed commit is not a commit object")
            if git("rev-parse", f"{record.reviewed_commit}^{{tree}}") != record.tree_sha:
                raise ValueError("reviewed commit does not match endorsed tree")
            matching_reviewers: set[str] = set()
            for source in review_sources:
                review_author = source.get("author")
                if (source.get("kind") != "review" or not completed_review(source)
                    or not isinstance(review_author, str)
                    or review_author.casefold().removesuffix("[bot]") not in reviewers):
                    continue
                reviewed = source.get("validated_sha")
                if not isinstance(reviewed, str) or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", reviewed):
                    raise ValueError("completed review lacks a validated commit")
                if (git("cat-file", "-t", reviewed) != "commit"
                    or git("rev-parse", f"{reviewed}^{{tree}}") != source.get("tree_sha")
                    or git("merge-base", reviewed, head) != reviewed):
                    raise ValueError("completed review is outside current ancestry or its recorded tree")
                matching_reviewers.add(review_author.casefold().removesuffix("[bot]"))
            if len(matching_reviewers) < required_review_count:
                raise ValueError(
                    "completed independent review coverage is incomplete"
                )
            actual = {source.url: source.sha256 for source in record.sources}
            for source in sorted(set(expected) | set(actual)):
                if expected.get(source) != actual.get(source):
                    gaps.append({"source": source, "reason": "missing, changed or extra endorsed finding"})
            if actual != expected:
                continue
            for proof in record.proofs:
                if git("rev-parse", f"{head}:{proof.path}") != proof.blob_sha:
                    raise ValueError(f"proof artifact changed: {proof.path}")
                if git("cat-file", "-t", proof.blob_sha) != "blob":
                    raise ValueError(f"proof artifact is not a blob: {proof.path}")
                metadata = git("ls-tree", head, "--", proof.path).split(maxsplit=3)
                if len(metadata) != 4 or metadata[0] not in {"100644", "100755"} or metadata[2] != proof.blob_sha:
                    raise ValueError(f"proof artifact is not a regular tracked file: {proof.path}")
            accepted.append({"author": author, "url": url, "reviewed_commit": record.reviewed_commit,
                             "tree_sha": record.tree_sha, "head_sha": head,
                             "sources": sorted(actual), "proof_count": len(record.proofs),
                             "completed_reviewers": sorted(matching_reviewers)})
        except (ValueError, ValidationError, subprocess.CalledProcessError) as exc:
            gaps.append({"source": url, "reason": str(exc).splitlines()[0]})
    if not accepted and not gaps:
        gaps = [{"source": source, "reason": "no independently endorsed repair evidence"}
                for source in sorted(expected)]
    return accepted, gaps
