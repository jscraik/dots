"""Replay supplied finding histories; never authenticate evidence or grant readiness."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StringConstraints,
    field_validator,
    model_validator,
)


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


Text = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4096)
]


class Revision(RootModel[str]):
    root: Annotated[str, StringConstraints(strict=True, pattern="^[0-9a-f]{40}$")]


class Subject(RootModel[str]):
    root: Annotated[
        str, StringConstraints(strict=True, pattern="^finding_[a-z0-9_-]{1,64}$")
    ]


class Actor(RootModel[str]):
    root: Annotated[
        str, StringConstraints(strict=True, pattern="^actor_[a-z0-9_-]{1,64}$")
    ]


class RunId(RootModel[str]):
    root: Annotated[
        str, StringConstraints(strict=True, pattern="^run_[a-z0-9_-]{1,64}$")
    ]


class PullNumber(RootModel[int]):
    root: Annotated[int, Field(strict=True, ge=1)]


class LineNumber(RootModel[int]):
    root: Annotated[int, Field(strict=True, ge=1)]


class Repository(RootModel[str]):
    root: Annotated[
        str, StringConstraints(strict=True, pattern="^[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+$")
    ]


class EvidenceRef(RootModel[str]):
    root: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=2048)]

    @field_validator("root")
    @classmethod
    def public_github_reference(cls, value: str) -> str:
        """Accept bounded HTTPS GitHub references without fetching their content."""
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "github.com"
            or parsed.query
            or re.search("[\\s\\x00-\\x1f\\x7f]", value)
        ):
            raise ValueError("evidence must be a public GitHub reference")
        return value


class SourcePath(RootModel[str]):
    root: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=1024)]

    @field_validator("root")
    @classmethod
    def portable_path(cls, value: str) -> str:
        """Reject absolute, traversing and platform-specific source paths."""
        if (
            value.startswith("/")
            or "\\" in value
            or ":" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or re.search("[\\x00-\\x1f\\x7f]", value)
        ):
            raise ValueError("source path must be portable and relative")
        return value


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Observation(Record):
    subject: Subject
    anchor: Text
    invariant: Text
    path: SourcePath
    line: LineNumber
    lens: Literal["correctness", "security", "architecture", "evidence", "operations"]
    consequence: Text
    confidence: Literal["tentative", "supported", "confirmed"]
    severity: Literal["P0", "P1", "P2", "P3"]
    blocking: bool
    evidence_ref: EvidenceRef


class Response(Record):
    subject: Subject
    action: Literal["fix", "refute", "decline"]
    reason: Text
    evidence_ref: EvidenceRef


class Recheck(Record):
    subject: Subject
    result: Literal["verified_fixed", "refuted", "still_present", "unverified"]
    checked_head: Revision
    reviewer: Actor
    reason: Text
    evidence_ref: EvidenceRef


class ReviewRun(Record):
    run_id: RunId
    observed_at: AwareDatetime
    head_sha: Revision
    base_sha: Revision
    policy_revision: Revision
    reviewed_scope: Annotated[list[SourcePath], Field(min_length=1, max_length=1000)]
    outcome: Literal["completed", "failed", "unavailable", "incomplete"]
    reviewer: Actor
    evidence_ref: EvidenceRef
    findings: Annotated[list[Observation], Field(max_length=1000)]
    responses: Annotated[list[Response], Field(max_length=1000)]
    rechecks: Annotated[list[Recheck], Field(max_length=1000)]


class History(Record):
    schema_version: Literal["review-finding-history/v1"]
    repository: Repository
    pr_number: PullNumber
    base_sha: Revision
    head_sha: Revision
    policy_revision: Revision
    author: Actor
    reviewed_scope: Annotated[list[SourcePath], Field(min_length=1, max_length=1000)]
    runs: Annotated[list[ReviewRun], Field(min_length=1, max_length=1000)]

    @model_validator(mode="after")
    def bound_evidence_and_order(self) -> History:
        """Require ordered unique runs and repository-bound evidence; bind pull references to this PR."""
        seen = set()
        previous = None
        prefix = f"/{self.repository.root}/"
        for run in self.runs:
            if run.run_id.root in seen or (
                previous is not None and run.observed_at <= previous
            ):
                raise ValueError(
                    "run identity and chronological order must be unambiguous"
                )
            seen.add(run.run_id.root)
            previous = run.observed_at
            for item in (run, *run.findings, *run.responses, *run.rechecks):
                path = urlsplit(item.evidence_ref.root).path
                if not path.startswith(prefix):
                    raise ValueError("evidence belongs to another repository")
                tail = path[len(prefix) :]
                if tail.startswith("pull/"):
                    if tail != f"pull/{self.pr_number.root}":
                        raise ValueError("evidence belongs to another pull request")
                elif not re.fullmatch(
                    "(?:commit/[0-9a-f]{40}|blob/[0-9a-f]{40}/.+|actions/runs/[1-9][0-9]*)",
                    tail,
                ):
                    raise ValueError("unsupported evidence reference")
        return self


def _identity(packet: History, observation: Observation) -> str:
    """Bind normalized invariants and case-sensitive anchors to one repository PR."""
    normalized = [
        observation.anchor.strip(),
        " ".join(observation.invariant.split()).casefold(),
    ]
    value = json.dumps(
        [packet.repository.root, packet.pr_number.root, *normalized],
        separators=(",", ":"),
    )
    return "finding_" + hashlib.sha256(value.encode()).hexdigest()


def _occurrence(status: str, run: ReviewRun) -> dict[str, Any]:
    """Start an occurrence with independent observation, response and recheck history."""
    return {
        "status": status,
        "observed_heads": [run.head_sha.root],
        "response": None,
        "verification": None,
        "observations": [],
        "responses": [],
        "rechecks": [],
    }


def _observe(packet: History, run: ReviewRun, rows: dict, aliases: dict) -> set[str]:
    """Retain observations, reopen closed findings and reject conflicting aliases."""
    observed: set[str] = set()
    for observation in run.findings:
        key, subject = (_identity(packet, observation), observation.subject.root)
        if subject in aliases and aliases[subject] != key:
            raise ValueError(
                "a finding subject was reused for a different invariant or anchor"
            )
        aliases[subject] = key
        if key not in rows:
            rows[key] = {
                "finding_id": key,
                "subjects": [],
                "anchor": observation.anchor,
                "invariant": observation.invariant,
                "occurrence_history": [_occurrence("open", run)],
            }
        row = rows[key]
        current = row["occurrence_history"][-1]
        if current["status"] in {"verified_fixed", "refuted"}:
            current = _occurrence("reopened", run)
            row["occurrence_history"].append(current)
        if subject not in row["subjects"]:
            row["subjects"].append(subject)
        if run.head_sha.root not in current["observed_heads"]:
            current["observed_heads"].append(run.head_sha.root)
        current["observations"].append(
            {
                **observation.model_dump(mode="json"),
                "run_id": run.run_id.root,
                "head_sha": run.head_sha.root,
                "reviewer": run.reviewer.root,
            }
        )
        for field in ("path", "line", "lens", "consequence", "confidence", "severity"):
            row[field] = observation.model_dump(mode="json")[field]
        row["blocking"] = row.get("blocking", False) or observation.blocking
        if current["status"] == "unverified":
            current["status"] = "open"
        observed.add(key)
    return observed


def _subject_row(subject: Subject, rows: dict, aliases: dict) -> dict:
    """Resolve a response subject only after its finding has been observed."""
    if subject.root not in aliases:
        raise ValueError("response or recheck has no preceding finding")
    return rows[aliases[subject.root]]


def _recheck(
    packet: History, run: ReviewRun, rows: dict, aliases: dict, observed: set[str]
) -> None:
    """Retain responses and accept closure only from matching independent rechecks."""
    checked: set[str] = set()
    for response in run.responses:
        row = _subject_row(response.subject, rows, aliases)
        current = row["occurrence_history"][-1]
        if current["status"] in {"verified_fixed", "refuted"}:
            current["status"] = "unverified"
            current["verification"] = None
        current["response"] = {
            **response.model_dump(mode="json"),
            "head_sha": run.head_sha.root,
            "actor": packet.author.root,
            "run_id": run.run_id.root,
        }
        current["responses"].append(current["response"])
    for check in run.rechecks:
        row = _subject_row(check.subject, rows, aliases)
        key = row["finding_id"]
        if key in checked:
            raise ValueError("multiple rechecks of one finding in the same run")
        checked.add(key)
        current = row["occurrence_history"][-1]
        current["verification"] = {
            **check.model_dump(mode="json"),
            "run_id": run.run_id.root,
        }
        current["rechecks"].append(current["verification"])
        valid = (
            run.outcome == "completed"
            and check.checked_head == run.head_sha
            and (check.reviewer != packet.author)
            and (run.reviewer != packet.author)
            and (run.base_sha == packet.base_sha)
            and (run.policy_revision == packet.policy_revision)
            and (row["path"] in {path.root for path in run.reviewed_scope})
        )
        expected_action = {"verified_fixed": "fix", "refuted": "refute"}.get(
            check.result
        )
        response = current["response"]
        if check.result in {"verified_fixed", "refuted"}:
            valid = (
                valid
                and key not in observed
                and (response is not None)
                and (response["action"] == expected_action)
                and (response["head_sha"] == run.head_sha.root)
            )
        current["status"] = check.result if valid else "unverified"
        if key in observed:
            current["status"] = "open"


def reconcile_history(raw: object) -> dict[str, Any]:
    """Return supplied-evidence diagnostics only, with no live clearance authority."""
    packet = History.model_validate_json(json.dumps(raw, allow_nan=False))
    rows: dict[str, dict] = {}
    aliases: dict[str, str] = {}
    for run in packet.runs:
        observed = _observe(packet, run, rows, aliases)
        _recheck(packet, run, rows, aliases, observed)
    findings = []
    for row in rows.values():
        current = row["occurrence_history"][-1]
        disposition = current["status"]
        if (
            disposition in {"verified_fixed", "refuted"}
            and current["verification"]["checked_head"] != packet.head_sha.root
        ):
            disposition = "unverified"
        findings.append(
            {
                **row,
                "occurrences": len(row["occurrence_history"]),
                "status": disposition,
                "response": current["response"],
                "verification": current["verification"],
            }
        )
    latest = packet.runs[-1]
    verified = (
        latest.outcome == "completed"
        and latest.head_sha == packet.head_sha
        and (latest.base_sha == packet.base_sha)
        and (latest.policy_revision == packet.policy_revision)
        and (
            {path.root for path in latest.reviewed_scope}
            == {path.root for path in packet.reviewed_scope}
        )
        and (latest.reviewer != packet.author)
    )
    status = "no_blocking_findings"
    if any(
        row["blocking"] and row["status"] in {"open", "reopened", "still_present"}
        for row in findings
    ):
        status = "blocked"
    elif not verified or any(
        row["blocking"] and row["status"] == "unverified" for row in findings
    ):
        status = "unverified"
    return {
        "service": "pr-finding-history",
        "schema_version": "review-finding-reconciliation/v1",
        "evidence_mode": "supplied_offline",
        "readiness_claimed": False,
        "repository": packet.repository.root,
        "pr_number": packet.pr_number.root,
        "base_sha": packet.base_sha.root,
        "head_sha": packet.head_sha.root,
        "policy_revision": packet.policy_revision.root,
        "review_outcome": latest.outcome,
        "reviewed_scope": [path.root for path in packet.reviewed_scope],
        "runs": [
            run.model_dump(mode="json", exclude={"findings", "responses", "rechecks"})
            for run in packet.runs
        ],
        "reconciliation_status": status,
        "findings": findings,
    }


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON keys instead of silently replacing supplied evidence."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def main() -> int:
    """Read one bounded regular JSON file and emit diagnostics without modifying it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packet", type=Path)
    args = _fixture_args(parser.parse_args())
    try:
        descriptor = _fixture_resource(os).open(
            args.packet, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        )
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("packet must be a regular file")
            data = stream.read(1048577)
        if len(data) > 1048576:
            raise ValueError("packet exceeds 1 MiB")
        result = reconcile_history(
            json.loads(data.decode("utf-8"), object_pairs_hook=_unique_fields)
        )
    except (OSError, ValueError, TypeError, RecursionError):
        print(
            json.dumps(
                {
                    "service": "pr-finding-history",
                    "status": "invalid",
                    "readiness_claimed": False,
                    "error": "invalid supplied history packet",
                }
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    _fixture_scope().admit_file(__file__)
    raise SystemExit(main())
