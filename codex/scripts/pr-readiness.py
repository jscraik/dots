"""Run the phase-aware, evidence-first pull-request readiness gate.

The create phase proves that a pushed branch has current remote ancestry, an
explicit scope, and a clean worktree before a PR may be created. The update
phase additionally proves that the hosted PR points at the current head and
that its reported checks and reviews are current. A receipt is bound to the
branch, head, base, phase, and scope digest so hooks can reject stale proof.

Use --phase update --export-review-clearance to print an incomplete source-bound
disposition template. Export does not write a receipt or grant review clearance.
Export requires two matching source inventories and fails closed on drift or a
failed recheck; this detects observed changes, not an atomic GitHub snapshot.

Committed scope includes deletions and both sides of renames. Paths are read
without Git quoting; non-UTF-8, line-breaking, and outer-whitespace names fail
closed because the UTF-8 line-based scope file cannot declare them exactly.
"""

from __future__ import annotations

import importlib.util as _scope_import
from pathlib import Path as _ScopePath

_scope_spec = _scope_import.spec_from_file_location(
    'dots_migration_scope', _ScopePath(__file__).resolve().with_name('migration_scope.py'))
if _scope_spec is None or _scope_spec.loader is None:
    raise RuntimeError('Disposable migration scope is unavailable')
_scope = _scope_import.module_from_spec(_scope_spec)
_scope_spec.loader.exec_module(_scope)
require_policy_environment = _scope.require_policy_environment
require_policy_scope = _scope.require_policy_scope
require_policy_path = _scope.require_policy_path
require_policy_output = _scope.require_policy_output

require_policy_scope()
require_policy_environment()

import argparse  # noqa: E402
import hashlib  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import signal  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
from collections.abc import Callable  # noqa: E402
from datetime import UTC, datetime  # noqa: E402
from functools import lru_cache  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402
from urllib.parse import quote, urlsplit  # noqa: E402


@lru_cache(maxsize=1)
def _coderabbit_summary_adapter() -> Any:
    """Load the trusted sibling only when structured review evidence needs it."""
    # Legacy reply parsing imports this entrypoint alone with Python -I. Do not
    # add a new import-time dependency or restore the caller's path to sys.path.
    spec = importlib.util.spec_from_file_location(
        "pr_coderabbit_summary", Path(__file__).resolve().with_name("pr_coderabbit_summary.py"))
    if spec is None or spec.loader is None:
        raise ImportError("CodeRabbit summary adapter is unavailable")
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    return adapter

SCHEMA_VERSION = "pr-readiness/v1"
SERVICE_NAME = "pr-readiness"
PHASES = ("create", "review_inspection", "review_reconciliation", "update")
TRUSTED_REMOTE = "origin"
RECEIPT_LANES = (
    "remote_ancestry",
    "dirty_worktree",
    "worktree_boundary",
    "scope",
    "pull_request",
    "required_checks",
    "reviews",
)
REVIEW_WAIVER_SCHEMA = "pr-readiness-review-waiver/v1"
REQUIRED_CHECK_POLICY_SCHEMA = "required-check-policy/v1"
REVIEW_WAIVER_SCOPE = "missing independent bot approvals only"
REVIEW_WAIVER_GOVERNANCE_FIELDS = (
    "rule_or_section",
    "tracking_ticket",
    "expiry_or_adr",
)
SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
SCOPE_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_TIMEOUT = 15
REPLY_TIMEOUT = 30
SUCCESS_CHECKS = {"success", "successful"}
PENDING_CHECKS = {"queued", "pending", "in_progress", "requested", "waiting", "expected"}
FAILED_CHECKS = {"failure", "failed", "error", "cancelled", "timed_out", "startup_failure", "action_required"}
BOT_REVIEWERS = {
    "coderabbitai": "CodeRabbit",
    "chatgpt-codex-connector": "Codex",
    "tessl-reviewer": "Tessl Reviewer",
}
REQUIRED_BOT_REVIEWERS = {login: BOT_REVIEWERS[login] for login in ("coderabbitai", "chatgpt-codex-connector")}
BOT_REVIEW_NO_FINDINGS_RE = re.compile(
    r"\bno\s+(?:actionable\s+)?(?:comments?|findings?)\b",
    re.IGNORECASE,
)
BOT_REVIEW_BLOCKED_RE = re.compile(
    r"\b(?:quota\s+(?:exceeded|exhausted|limit(?:s|ed)?)|usage\s+limits?|rate[- ]limited|rate\s+limit|review\s+failed|review\s+error|unable\s+to\s+review|error\s*:\s*review\s+unavailable)\b",
    re.IGNORECASE,
)
BOT_REPLY_STATUS_PATTERN = (
    r"^\s*(?:(?:error|review\s+unavailable)\s*:\s*)?"
    r"(?:(?:API\s+)?rate\s+limit(?:\s+(?:exceeded|reached))?|rate[- ]limited|"
    r"review\s+(?:failed|error|unavailable)|unable\s+to\s+review|"
    r"quota\s+(?:exceeded|exhausted|limit(?:s|ed)?)|usage\s+limits?|"
    r"(?:authentication|authorization)\s+(?:failed|error|denied)|"
    r"(?:(?:HTTP\s+)?401\s+)?unauthorized|(?:HTTP\s+)?403\s+forbidden|permission\s+denied)"
)
BOT_REPLY_BLOCKED_RE = re.compile(
    BOT_REPLY_STATUS_PATTERN +
    r"(?:\s*:\s*(?:quota\s+(?:exceeded|exhausted)|(?:API\s+)?rate\s+limit\s+(?:exceeded|reached)))?"
    r"[.!]?(?:\s+(?:Please\s+)?(?:try\s+again\s+later|retry\s+the\s+request)[.!]?)?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
BOT_OUTPUT_DIAGNOSTIC_RE = re.compile(
    BOT_REPLY_STATUS_PATTERN + r"[.!]?[ \t]*:[ \t]*\S[^\r\n]*$",
    re.IGNORECASE | re.MULTILINE,
)
AUTH_FAILURE_SEQUENCE_RE = re.compile(
    r"\b(?:auth|authentication|authorization)\b(?:\s+[a-z0-9_-]+){0,3}\s+"
    r"\b(?:failed|failure|denied|blocked|unavailable|expired)\b"
    r"(?=\s*(?:$|[.!?:;,]|while\b|during\b|from\b|on\b|request\b|response\b|review\b|reviewing\b))",
    re.IGNORECASE,
)
UNAUTHORIZED_RESPONSE_RE = re.compile(
    r"(?:\b401\s+unauthori[sz]ed\b|\bunauthori[sz]ed(?=$|[.:;!?])|\bunauthori[sz]ed\s+(?:response|error|credentials?|login|token)\b)",
    re.IGNORECASE,
)
STANDALONE_AUTH_RESPONSE_RE = re.compile(
    r"(?:^\s*(?:http\s*)?401(?:\s+unauthori[sz]ed)?[.!]?\s*$|^\s*unauthori[sz]ed request[.!]?\s*$)",
    re.IGNORECASE,
)
# Match an actual unauthorized response line, rather than every prose mention
# of 401. Review text may discuss an implementation that intentionally returns
# HTTP 401; response evidence must be bare, explicitly unauthorized, or carry
# a credential failure marker.
AUTH_STATUS_RESPONSE_RE = re.compile(
    r"(?im)^\s*(?:http\s*)?401(?:\s+unauthori[sz]ed\b|\s*[:,-]\s*(?:bad|invalid)\s+credentials?\b.*|\s*[.!]?\s*)$"
)
PERMISSION_DENIED_RESPONSE_RE = re.compile(
    r"(?im)^(?:\s*(?:http\s*)?403(?:\s+forbidden\b|\s*$).*|\s*resource\s+not\s+accessible\s+by\s+integration[.!]?\s*)$"
)
AUTH_ERROR_RESPONSE_RE = re.compile(
    r"\b(?:auth|authentication|authorization)\s+error\b"
    r"(?=\s*(?:$|[.!?:;,]|while\b|during\b|from\b|on\b|request\b|response\b|review\b|reviewing\b))",
    re.IGNORECASE,
)
CREDENTIAL_FAILURE_RESPONSE_RE = re.compile(
    r"(?im)^\s*(?:bad|invalid)\s+credentials?\b.*$|^\s*credentials?\s+expired\b.*$",
)
EXPLICIT_SHA_BINDING_RE = re.compile(
    r"\b(?:commit|sha(?:-?1)?|head|revision|ref|for)\b"
    r"(?:\s+(?:commit|sha(?:-?1)?|head|revision|ref))?"
    r"\s*(?::|=|#|is|of|for)?\s*([0-9a-f]{7,64})\b",
    re.IGNORECASE,
)


class CommandFailure(RuntimeError):
    def __init__(self, command: list[str], reason: str) -> None:
        self.command = command
        self.reason = reason
        super().__init__(reason)


def run_command(command: list[str], cwd: Path, *, check: bool = True, timeout: int = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        if check:
            raise CommandFailure(command, str(exc)) from exc
        return subprocess.CompletedProcess(command, 1, "", str(exc))
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "command failed").strip().splitlines()[0]
        raise CommandFailure(command, detail)
    return result


def git(root: Path, *args: str, check: bool = True) -> str:
    result = run_command(["git", *args], root, check=check)
    return result.stdout.strip()


def lane(status: str, evidence: str, **details: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"status": status, "evidence": evidence}
    if details:
        result["details"] = details
    return result


def load_review_waiver(path: Path, pr_number: int, head_sha: str, repository: Path | None = None) -> tuple[dict[str, Any] | None, str | None]:
    """Load and bind an explicit operator waiver to one PR head."""
    try:
        raw = _scope.policy_repository_read(repository or Path.cwd(), path)
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"review waiver could not be read: {exc}"
    if not isinstance(payload, dict):
        return None, "review waiver must be a JSON object"
    expected_keys = {
        "schema_version",
        "pr_number",
        "head_sha",
        "scope",
        "authorized_by",
        "reason",
        *REVIEW_WAIVER_GOVERNANCE_FIELDS,
    }
    if set(payload) != expected_keys:
        return None, "review waiver must contain exactly the required fields"
    if payload.get("schema_version") != REVIEW_WAIVER_SCHEMA:
        return None, "review waiver schema_version is not pr-readiness-review-waiver/v1"
    if payload.get("pr_number") != pr_number:
        return None, "review waiver PR number does not match the hosted PR"
    if payload.get("head_sha") != head_sha:
        return None, "review waiver head does not match the current PR head"
    if payload.get("scope") != REVIEW_WAIVER_SCOPE:
        return None, "review waiver scope is not the narrow independent-review waiver"
    if not isinstance(payload.get("authorized_by"), str) or not payload["authorized_by"].strip():
        return None, "review waiver authorized_by is required"
    if not isinstance(payload.get("reason"), str) or not payload["reason"].strip():
        return None, "review waiver reason is required"
    for field in REVIEW_WAIVER_GOVERNANCE_FIELDS:
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            return None, f"review waiver {field} is required"
    return {
        **payload,
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }, None


def validate_review_waiver_record(record: dict[str, Any], pr_number: int, head_sha: str, repository: Path | None = None) -> tuple[dict[str, Any] | None, str | None]:
    """Re-read a receipt-bound waiver so the file cannot be swapped later."""
    path_value = record.get("path")
    digest = record.get("sha256")
    if not isinstance(path_value, str) or not isinstance(digest, str):
        return None, "receipt-bound review waiver is missing path or digest"
    waiver, error = load_review_waiver(Path(path_value), pr_number, head_sha, repository)
    if error or waiver is None:
        return None, error or "review waiver could not be loaded"
    if waiver["sha256"] != digest:
        return None, "receipt-bound review waiver digest changed"
    return waiver, None


def blocker(code: str, reason: str) -> dict[str, str]:
    return {"code": code, "reason": reason}


def add_service_identity(payload: dict[str, Any]) -> dict[str, Any]:
    """Add service identity to emitted result/error payloads, not receipts."""
    return {"service": SERVICE_NAME, **payload}


def resolve_root(value: Path | None) -> Path:
    root = (value or Path.cwd()).expanduser().resolve()
    result = run_command(["git", "rev-parse", "--show-toplevel"], root, check=False)
    if result.returncode != 0:
        raise CommandFailure(["git", "rev-parse", "--show-toplevel"], "repository root could not be resolved")
    return Path(result.stdout.strip()).resolve()


def current_worktree(root: Path) -> tuple[str, str, str, str, str]:
    branch = git(root, "branch", "--show-current")
    if not branch:
        branch = "(detached)"
    head = git(root, "rev-parse", "HEAD")
    base_branch = git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD", check=False)
    if base_branch.startswith("origin/"):
        base_branch = base_branch.removeprefix("origin/")
    return branch, head, base_branch or "main", git(root, "rev-parse", "--git-dir"), git(root, "rev-parse", "--git-common-dir")


def remote_sha(root: Path, remote: str, ref: str) -> str | None:
    """Read the trusted hosted branch without invoking Git remote machinery."""
    if remote != TRUSTED_REMOTE:
        return None
    repository, error = repository_slug(root)
    if error or repository is None:
        return None
    return hosted_remote_sha(root, repository, ref)


def parse_scope(path: Path, root: Path) -> tuple[list[str], str]:
    try:
        raw = _scope.policy_repository_read(root, path).decode("utf-8")
    except OSError as exc:
        return [], f"scope file could not be read: {exc}"
    entries: list[str]
    if path.suffix == ".json":
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            return [], f"scope JSON is invalid: {exc.msg}"
        entries = payload if isinstance(payload, list) else []
        if not isinstance(payload, list):
            return [], "scope JSON must be an array of repository-relative paths"
    else:
        entries = [line.strip() for line in raw.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    normalized: list[str] = []
    for item in entries:
        if not isinstance(item, str) or not item.strip():
            return [], "scope entries must be non-empty strings"
        candidate = item.strip().replace(os.sep, "/")
        path_obj = Path(candidate)
        if path_obj.is_absolute() or candidate == ".." or candidate.startswith("../"):
            return [], f"scope path must stay repository-relative: {candidate}"
        normalized.append(candidate)
    normalized = sorted(set(normalized))
    digest = hashlib.sha256(("\n".join(normalized) + "\n").encode("utf-8")).hexdigest()
    return normalized, digest


def is_scope_digest(value: str | None) -> bool:
    """Distinguish a successful scope digest from a parse-error message."""
    return value is not None and SCOPE_DIGEST_RE.fullmatch(value) is not None


def changed_file_records(root: Path, base_sha: str, head_sha: str) -> list[dict[str, str]]:
    """Read complete committed paths and modes without Git quoting or renames."""
    command = ["git", "diff", "--raw", "--no-renames", "--no-abbrev",
               "--no-ext-diff", "--no-textconv", "-z", f"{base_sha}...{head_sha}"]
    try:
        result = subprocess.run(command, cwd=root, capture_output=True,
                                timeout=DEFAULT_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CommandFailure(command, str(exc)) from exc
    if result.returncode:
        raise CommandFailure(command, "committed-path diff failed")
    try:
        output = result.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CommandFailure(command, "non-UTF-8 paths cannot be represented by the scope contract") from exc
    if output and not output.endswith("\0"):
        raise CommandFailure(command, "changed-path response is not NUL terminated")
    fields = output.split("\0")[:-1] if output else []
    if len(fields) % 2:
        raise CommandFailure(command, "changed-path response has incomplete records")
    records = []
    for index in range(0, len(fields), 2):
        metadata, path = fields[index:index + 2]
        match = re.fullmatch(r":([0-7]{6}) ([0-7]{6}) ([0-9a-f]{40}(?:[0-9a-f]{24})?) ([0-9a-f]{40}(?:[0-9a-f]{24})?) [AMDT]", metadata)
        if not match or not path or path.startswith("/") or any(part in {"", ".", ".."} for part in path.split("/")):
            raise CommandFailure(command, "changed-path response has invalid metadata or path")
        if len(match[3]) != len(match[4]):
            raise CommandFailure(command, "changed-path object IDs have inconsistent lengths")
        if path.splitlines() != [path] or path != path.strip():
            raise CommandFailure(command, "changed path cannot be represented by the line-based scope contract")
        records.append({"path": path, "old_mode": match[1], "new_mode": match[2]})
    return records


def changed_paths(root: Path, base_sha: str, head_sha: str) -> list[str]:
    return sorted({record["path"] for record in changed_file_records(root, base_sha, head_sha)})


def worktree_lane(root: Path) -> dict[str, Any]:
    output = git(root, "worktree", "list", "--porcelain", check=False)
    entries: list[dict[str, str]] = []
    current = root.resolve()
    path: str | None = None
    for line in output.splitlines() + [""]:
        if line.startswith("worktree "):
            path = line.removeprefix("worktree ")
        elif line == "" and path:
            entries.append({"path": str(Path(path).resolve())})
            path = None
    registered = any(Path(item["path"]).resolve() == current for item in entries)
    if not registered:
        return lane("fail", "current checkout is not registered with git worktree", entries=entries)
    return lane("pass", "current checkout is registered with git worktree", entries=entries, linked=len(entries) > 1)


def dirty_lane(root: Path) -> dict[str, Any]:
    result = run_command(["git", "status", "--porcelain=v1"], root, check=False)
    if result.returncode:
        return lane("blocked", "worktree status is unavailable")
    paths = [line[3:] for line in result.stdout.splitlines() if len(line) >= 4]
    if paths:
        return lane("fail", f"worktree has {len(paths)} dirty path(s)", paths=paths)
    return lane("pass", "worktree is clean", paths=[])


def gh_pr(root: Path, *, for_export: bool = False, number: int | None = None) -> tuple[dict[str, Any] | None, str | None]:
    fields = "number,url,state,author,headRefName,headRefOid,baseRefName,baseRefOid,isDraft,reviewDecision,reviews,statusCheckRollup"
    target = [] if number is None else [str(number)]
    result = run_command(["gh", "pr", "view", *target, "--json", fields], root, check=False)
    if result.returncode != 0:
        text = (result.stderr or result.stdout).strip().lower()
        if "no pull requests found" in text or "could not resolve to a pull request" in text:
            return None, None
        return None, (result.stderr or result.stdout or "gh pr view failed").strip().splitlines()[0]
    try:
        pr = json.loads(result.stdout)
        if not isinstance(pr, dict) or type(pr.get("number")) is not int or pr["number"] <= 0:
            return None, "hosted PR identity is malformed"
        slug, error = repository_slug(root)
        if error or not slug:
            return None, error or "repository unavailable for complete review query"
        # The summary view is not proof of complete historical review coverage.
        hostname, error = review_repository_host(pr, slug)
        if error or not hostname:
            return None, error or "repository host unavailable"
        policy, check_evidence, error = required_checks_snapshot(
            root,
            slug,
            pr.get("baseRefName"),
            pr.get("baseRefOid"),
            pr.get("headRefOid"),
            hostname,
        )
        policy_error = error
        reviews, error = review_inventory_collection(root, f"repos/{slug}/pulls/{pr['number']}/reviews", hostname)
        if error:
            return None, error
        if any(_review_login(review) == "tessl-reviewer" for review in reviews):
            tessl_checks, error = tessl_check_inventory(root, slug, pr.get("headRefOid"), hostname)
            if error:
                return None, error
            pr = {**pr, "tessl_check_runs": tessl_checks}
        return {
            **pr,
            "requiredCheckPolicy": policy,
            "reviews": reviews,
            "requiredCheckEvidence": check_evidence,
            "requiredCheckPolicyError": policy_error,
        }, None
    except json.JSONDecodeError as exc:
        return None, f"gh pr view returned invalid JSON: {exc.msg}"


def repository_slug(root: Path, *, required_host: str | None = None) -> tuple[str | None, str | None]:
    fields = "nameWithOwner,url" if required_host else "nameWithOwner"
    result = run_command(["gh", "repo", "view", "--json", fields], root, check=False)
    if result.returncode != 0:
        return None, (result.stderr or result.stdout or "gh repo view failed").strip().splitlines()[0]
    try:
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict):
            return None, "gh repo view returned invalid repository metadata: expected an object"
        value = payload.get("nameWithOwner")
    except json.JSONDecodeError as exc:
        return None, f"gh repo view returned invalid JSON: {exc.msg}"
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value) or any(segment in {".", ".."} for segment in value.split("/")):
        return None, "gh repo view returned an invalid repository identity"
    if required_host and payload.get("url") != f"https://{required_host}/{value}":
        return None, "gh repo view returned a repository on an unexpected host"
    return value, None


def hosted_remote_sha(root: Path, repository: str, ref: str) -> str | None:
    """Read one exact GitHub branch without consulting workspace Git configuration."""
    if (not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
            or any(segment in {".", ".."} for segment in repository.split("/"))
            or not isinstance(ref, str) or not ref
            or any(character in ref for character in "\x00\r\n")):
        return None
    endpoint = f"repos/{repository}/git/ref/heads/{quote(ref, safe='')}"
    result = run_command(["gh", "api", endpoint], root, check=False)
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    git_object = payload.get("object")
    if not isinstance(git_object, dict):
        return None
    sha = git_object.get("sha")
    if (payload.get("ref") != f"refs/heads/{ref}"
            or git_object.get("type") != "commit"
            or not isinstance(sha, str)
            or SHA_RE.fullmatch(sha) is None):
        return None
    return sha


def _parse_review_thread_page(
    raw: str,
    page_number: int,
) -> tuple[list[dict[str, Any]], bool, str | None, str | None]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [], False, None, f"review-thread response page {page_number} was invalid: {exc}"
    if not isinstance(payload, dict):
        return [], False, None, f"review-thread response page {page_number} was invalid: response must be an object"
    if "errors" in payload:
        errors = payload["errors"]
        if not isinstance(errors, list):
            return [], False, None, f"review-thread response page {page_number} was invalid: errors must be an array"
        return [], False, None, f"review-thread response page {page_number} contained GraphQL errors"
    data = payload.get("data")
    if not isinstance(data, dict):
        return [], False, None, f"review-thread response page {page_number} was invalid: data must be an object"
    repository = data.get("repository")
    if not isinstance(repository, dict):
        return [], False, None, f"review-thread response page {page_number} was invalid: repository must be an object"
    pull_request = repository.get("pullRequest")
    if not isinstance(pull_request, dict):
        return [], False, None, f"review-thread response page {page_number} was invalid: pullRequest must be an object"
    threads = pull_request.get("reviewThreads")
    if not isinstance(threads, dict):
        return [], False, None, f"review-thread response page {page_number} was invalid: reviewThreads must be an object"
    nodes = threads.get("nodes")
    page_info = threads.get("pageInfo")
    if not isinstance(nodes, list) or not all(isinstance(node, dict) for node in nodes):
        return [], False, None, f"review-thread response page {page_number} was invalid: nodes must be objects"
    for index, node in enumerate(nodes):
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id or len(node_id) > 256:
            return [], False, None, f"review-thread response page {page_number} was invalid: node {index} id must be a nonempty string of at most 256 characters"
        if not isinstance(node.get("isResolved"), bool):
            return [], False, None, f"review-thread response page {page_number} was invalid: node {index} isResolved must be boolean"
    if not isinstance(page_info, dict):
        return [], False, None, f"review-thread response page {page_number} was invalid: pageInfo must be an object"
    has_next_page = page_info.get("hasNextPage")
    if not isinstance(has_next_page, bool):
        return [], False, None, f"review-thread response page {page_number} was invalid: hasNextPage must be boolean"
    end_cursor = page_info.get("endCursor")
    if has_next_page and (not isinstance(end_cursor, str) or not end_cursor):
        return [], False, None, f"review-thread response page {page_number} was invalid: missing endCursor"
    return nodes, has_next_page, end_cursor if isinstance(end_cursor, str) else None, None


def review_threads(root: Path, number: int, head_sha: str) -> tuple[dict[str, Any], str | None]:
    slug, error = repository_slug(root)
    if error or not slug:
        return {}, error or "repository slug unavailable for review-thread query"
    owner, name = slug.split("/", 1)
    query = """query($owner:String!, $name:String!, $number:Int!, $cursor:String) {
      repository(owner:$owner, name:$name) {
        pullRequest(number:$number) {
          reviewThreads(first:100, after:$cursor) {
            pageInfo { hasNextPage endCursor }
            nodes { id isResolved comments(last:1) { nodes { commit { oid } } } }
          }
        }
      }
    }"""
    cursor: str | None = None
    seen_cursors: set[str] = set()
    pages = 0
    fetched_threads = 0
    unresolved = 0
    unresolved_thread_ids: list[str] = []
    while True:
        pages += 1
        command = [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={query}",
            "-f",
            f"owner={owner}",
            "-f",
            f"name={name}",
            "-F",
            f"number={number}",
        ]
        if cursor is not None:
            command.extend(["-f", f"cursor={cursor}"])
        result = run_command(command, root, check=False)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "review-thread query failed").strip().splitlines()[0]
            return {}, f"review-thread query page {pages} failed: {detail}"
        nodes, has_next_page, end_cursor, error = _parse_review_thread_page(result.stdout, pages)
        if error:
            return {}, error
        fetched_threads += len(nodes)
        unresolved += sum(1 for node in nodes if node["isResolved"] is False)
        unresolved_thread_ids.extend(
            node["id"]
            for node in nodes
            if node["isResolved"] is False
        )
        if not has_next_page:
            break
        if end_cursor is None:
            return {}, f"review-thread response page {pages} was invalid: missing endCursor"
        if end_cursor in seen_cursors:
            return {}, f"review-thread response page {pages} repeated endCursor"
        seen_cursors.add(end_cursor)
        cursor = end_cursor
    return {
        "unresolved_threads": unresolved,
        "unresolved_thread_ids": sorted(set(unresolved_thread_ids)),
        "truncated": False,
        "head_sha": head_sha,
        "pages": pages,
        "fetched_threads": fetched_threads,
    }, None


def _required_check_record(context: Any, app_id: Any) -> dict[str, Any]:
    if not isinstance(context, str) or not context or context != context.strip():
        raise ValueError("required check context is missing or malformed")
    if app_id is None or (type(app_id) is int and app_id == -1):
        normalized_app_id = None
    elif type(app_id) is int and app_id > 0:
        normalized_app_id = app_id
    else:
        raise ValueError("required check App identity is malformed")
    return {"context": context, "app_id": normalized_app_id}


def _required_check_sort_key(item: dict[str, Any]) -> tuple[str, int]:
    app_id = item["app_id"]
    return item["context"], -1 if app_id is None else app_id


def _required_check_policy(
    root: Path,
    slug: str,
    base_branch: Any,
    base_sha: Any,
    hostname: str,
) -> tuple[dict[str, Any], str | None]:
    """Read the complete provider policy that applies to one exact base ref."""
    if (
        not isinstance(base_branch, str)
        or not base_branch
        or not isinstance(base_sha, str)
        or not SHA_RE.fullmatch(base_sha)
    ):
        return {}, "required-check policy requires an exact PR base branch and commit"
    host_args = ["--hostname", hostname]
    encoded_branch = quote(base_branch, safe="")
    branch_path = f"repos/{slug}/branches/{encoded_branch}"
    branch_result = run_command(["gh", "api", branch_path, *host_args], root, check=False)
    if branch_result.returncode:
        return {}, "required-check branch policy inventory unavailable"
    rules_path = f"repos/{slug}/rules/branches/{encoded_branch}?per_page=100"
    rules_result = run_command(
        ["gh", "api", rules_path, *host_args, "--paginate", "--slurp"],
        root,
        check=False,
    )
    if rules_result.returncode:
        return {}, "required-check ruleset inventory unavailable"
    try:
        branch = json.loads(branch_result.stdout)
        pages = json.loads(rules_result.stdout)
        if (
            not isinstance(branch, dict)
            or branch.get("name") != base_branch
            or not isinstance(branch.get("commit"), dict)
            or branch["commit"].get("sha") != base_sha
            or not isinstance(branch.get("protected"), bool)
        ):
            raise ValueError("branch identity or protection state is malformed")
        if not isinstance(pages, list) or not pages or any(
            not isinstance(page, list) or any(not isinstance(rule, dict) for rule in page)
            for page in pages
        ):
            raise ValueError("ruleset pages are malformed")

        required: list[dict[str, Any]] = []
        protection = branch.get("protection")
        summary_required = protection.get("required_status_checks") if isinstance(protection, dict) else None
        summary_contexts = summary_required.get("contexts") if isinstance(summary_required, dict) else None
        fetched_classic = False
        # An authenticated unprotected branch plus the complete active-rule
        # inventory proves that no classic protection contributes checks.
        if branch['protected'] is False and protection is None:
            protection = {'required_status_checks': None}
        elif protection is None or (
            isinstance(protection, dict)
            and (not isinstance(summary_required, dict)
                 or not isinstance(summary_required.get("checks"), list))
        ):
            fetched_classic = True
            classic = run_command(['gh', 'api', branch_path + '/protection', *host_args],
                                  root, check=False)
            if classic.returncode:
                unavailable = json.loads(classic.stdout)
                if (not isinstance(unavailable, dict)
                        or unavailable.get('message') != 'Branch not protected'
                        or unavailable.get('status') != '404'
                        or 'HTTP 404' not in classic.stderr):
                    raise ValueError('classic branch protection inventory unavailable')
                protection = {'required_status_checks': None}
            else:
                protection = json.loads(classic.stdout)
        if not isinstance(protection, dict):
            raise ValueError("branch protection details are malformed")
        if "required_status_checks" not in protection:
            raise ValueError("branch required-status policy inventory is unavailable")
        branch_required = protection["required_status_checks"]
        branch_source: dict[str, Any] = {
            "kind": "branch_protection",
            "protected": branch["protected"],
            "enforcement_level": None,
            "required_status_checks": [],
        }
        if branch_required is not None:
            if not isinstance(branch_required, dict):
                raise ValueError("branch required-status policy is malformed")
            contexts = branch_required.get("contexts")
            checks = branch_required.get("checks")
            if not isinstance(contexts, list) or not isinstance(checks, list):
                raise ValueError("branch required-status identities are malformed")
            enforcement_level = branch_required.get("enforcement_level")
            if enforcement_level is not None and not isinstance(enforcement_level, str):
                raise ValueError("branch required-status enforcement is malformed")
            branch_source["enforcement_level"] = enforcement_level
            branch_checks = []
            for check in checks:
                if not isinstance(check, dict) or "app_id" not in check:
                    raise ValueError("branch required-status check is malformed")
                branch_checks.append(_required_check_record(check.get("context"), check["app_id"]))
            represented = {item["context"] for item in branch_checks}
            for context in contexts:
                if context not in represented:
                    if fetched_classic:
                        raise ValueError("classic protection is missing a required App identity")
                    branch_checks.append(_required_check_record(context, None))
            branch_checks = sorted(
                {(_required_check_sort_key(item)): item for item in branch_checks}.values(),
                key=_required_check_sort_key,
            )
            branch_source["required_status_checks"] = branch_checks
            required.extend(branch_checks)
        if isinstance(summary_contexts, list) and any(
            not any(item["context"] == context for item in required) for context in summary_contexts
        ):
            raise ValueError("branch protection details do not cover the summary contexts")

        ruleset_sources: list[dict[str, Any]] = []
        for rule in (rule for page in pages for rule in page):
            rule_type = rule.get("type")
            if not isinstance(rule_type, str) or not rule_type:
                raise ValueError("ruleset rule type is malformed")
            if rule_type == "workflows":
                return {}, "required workflow policy cannot be authenticated by the required-check lane"
            if rule_type != "required_status_checks":
                continue
            ruleset_id = rule.get("ruleset_id")
            if type(ruleset_id) is not int or ruleset_id <= 0:
                raise ValueError("required-status ruleset identity is malformed")
            parameters = rule.get("parameters")
            entries = parameters.get("required_status_checks") if isinstance(parameters, dict) else None
            if not isinstance(entries, list) or not entries:
                raise ValueError("required-status ruleset entries are malformed")
            strict = parameters.get("strict_required_status_checks_policy")
            do_not_enforce_on_create = parameters.get("do_not_enforce_on_create")
            if strict is not None and not isinstance(strict, bool):
                raise ValueError("required-status ruleset strictness is malformed")
            if do_not_enforce_on_create is not None and not isinstance(do_not_enforce_on_create, bool):
                raise ValueError("required-status ruleset creation policy is malformed")
            identities = []
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ValueError("required-status ruleset check is malformed")
                identities.append(
                    _required_check_record(entry.get("context"), entry.get("integration_id"))
                )
            identities = sorted(
                {(_required_check_sort_key(item)): item for item in identities}.values(),
                key=_required_check_sort_key,
            )
            for field in ("ruleset_source_type", "ruleset_source", "ruleset_name"):
                if rule.get(field) is not None and not isinstance(rule[field], str):
                    raise ValueError("required-status ruleset metadata is malformed")
            ruleset_sources.append(
                {
                    "kind": "ruleset",
                    "id": ruleset_id,
                    "name": rule.get("ruleset_name"),
                    "source": rule.get("ruleset_source"),
                    "source_type": rule.get("ruleset_source_type"),
                    "strict": strict,
                    "do_not_enforce_on_create": do_not_enforce_on_create,
                    "required_status_checks": identities,
                }
            )
            required.extend(identities)

        required = sorted(
            {(_required_check_sort_key(item)): item for item in required}.values(),
            key=_required_check_sort_key,
        )
        policy = {
            "schema_version": REQUIRED_CHECK_POLICY_SCHEMA,
            "repository": slug,
            "base_branch": base_branch,
            "base_sha": base_sha,
            "sources": [branch_source, *sorted(ruleset_sources, key=lambda item: item["id"])],
            "required_checks": required,
        }
        policy["digest"] = hashlib.sha256(
            json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return policy, None
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return {}, f"required-check policy inventory malformed: {exc}"


def _current_check_inventory(
    root: Path,
    slug: str,
    head_sha: Any,
    hostname: str,
) -> tuple[list[dict[str, Any]], str | None]:
    """Read exact-head statuses and check runs with provider App identities."""
    if not isinstance(head_sha, str) or not SHA_RE.fullmatch(head_sha):
        return [], "required-check evidence requires an exact PR head"
    host_args = ["--hostname", hostname]
    checks_result = run_command(
        [
            "gh",
            "api",
            f"repos/{slug}/commits/{head_sha}/check-runs?filter=all&per_page=100",
            *host_args,
            "--paginate",
            "--slurp",
        ],
        root,
        check=False,
    )
    if checks_result.returncode:
        return [], "current-head check-run inventory unavailable"
    statuses_result = run_command(
        [
            "gh",
            "api",
            f"repos/{slug}/commits/{head_sha}/statuses?per_page=100",
            *host_args,
            "--paginate",
            "--slurp",
        ],
        root,
        check=False,
    )
    if statuses_result.returncode:
        return [], "current-head status-context inventory unavailable"
    try:
        check_pages = json.loads(checks_result.stdout)
        status_pages = json.loads(statuses_result.stdout)
        if not isinstance(check_pages, list) or not check_pages or any(
            not isinstance(page, dict)
            or not isinstance(page.get("check_runs"), list)
            or any(not isinstance(check, dict) for check in page["check_runs"])
            for page in check_pages
        ):
            raise ValueError("check-run pages are malformed")
        if not isinstance(status_pages, list) or not status_pages or any(
            not isinstance(page, list) or any(not isinstance(status, dict) for status in page)
            for page in status_pages
        ):
            raise ValueError("status-context pages are malformed")

        evidence: list[dict[str, Any]] = []
        for check in (check for page in check_pages for check in page["check_runs"]):
            app = check.get("app")
            if (
                type(check.get("id")) is not int
                or check["id"] <= 0
                or not isinstance(check.get("node_id"), str)
                or not check["node_id"] or len(check["node_id"]) > 256
                or not isinstance(check.get("name"), str)
                or not check["name"]
                or check.get("head_sha") != head_sha
                or not isinstance(check.get("status"), str)
                or (check.get("conclusion") is not None and not isinstance(check["conclusion"], str))
                or not isinstance(app, dict)
                or type(app.get("id")) is not int
                or app["id"] <= 0
                or (app.get("slug") is not None and not isinstance(app["slug"], str))
            ):
                raise ValueError("check-run identity or lifecycle is malformed")
            evidence.append(
                {
                    "__typename": "CheckRun",
                    "id": check["id"],
                    "node_id": check["node_id"],
                    "name": check["name"],
                    "head_sha": head_sha,
                    "status": check["status"],
                    "conclusion": check.get("conclusion"),
                    "startedAt": check.get("started_at"),
                    "completedAt": check.get("completed_at"),
                    "app": {"id": app["id"], "slug": app.get("slug")},
                }
            )
        for status in (status for page in status_pages for status in page):
            if (
                type(status.get("id")) is not int
                or status["id"] <= 0
                or not isinstance(status.get("context"), str)
                or not status["context"]
                or ("sha" in status and status["sha"] != head_sha)
                or not isinstance(status.get("state"), str)
                or not isinstance(status.get("created_at"), str)
                or not status["created_at"]
            ):
                raise ValueError("status-context identity or lifecycle is malformed")
            evidence.append(
                {
                    "__typename": "StatusContext",
                    "id": status["id"],
                    "context": status["context"],
                    "head_sha": head_sha,
                    "state": status["state"],
                    "createdAt": status["created_at"],
                }
            )
        return _enrich_check_workflows(root, slug, head_sha, hostname, evidence)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return [], f"current-head check inventory malformed: {exc}"


def _enrich_check_workflows(
    root: Path, slug: str, head_sha: str, hostname: str, records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str | None]:
    """Join immutable CheckRun identity before evaluating workflow-aware reruns."""
    checks = [item for item in records if item.get("__typename") == "CheckRun"]
    by_node = {item['node_id']: item for item in checks}
    if len(by_node) != len(checks):
        return [], 'current-head check inventory has duplicate node identities'
    query = ('query($ids:[ID!]!){nodes(ids:$ids){__typename ... on CheckRun{'
             'id databaseId name status conclusion startedAt completedAt '
             'checkSuite{commit{oid} repository{nameWithOwner} '
             'workflowRun{workflow{id name}}}}}}')
    joined = {}
    for start in range(0, len(checks), 100):
        selected = checks[start:start + 100]
        command = ['gh', 'api', 'graphql', '--hostname', hostname, '-f', 'query=' + query]
        for item in selected:
            command.extend(['-f', 'ids[]=' + item['node_id']])
        result = run_command(command, root, check=False)
        if result.returncode:
            return [], 'required-check workflow identity inventory unavailable'
        try:
            payload = json.loads(result.stdout)
            if not isinstance(payload, dict) or 'errors' in payload:
                raise ValueError('GraphQL errors or malformed response')
            nodes = payload['data']['nodes']
            if not isinstance(nodes, list) or len(nodes) != len(selected):
                raise ValueError('incomplete check-node inventory')
            expected = {item['node_id'] for item in selected}
            for node in nodes:
                if not isinstance(node, dict) or node.get('__typename') != 'CheckRun':
                    raise ValueError('missing or invalid check node')
                identity = node.get('id')
                if not isinstance(identity, str) or identity not in expected or identity in joined:
                    raise ValueError('unexpected or duplicate check node')
                record = by_node[identity]
                suite = node['checkSuite']
                if (type(node.get('databaseId')) is not int or node['databaseId'] != record['id']
                        or node.get('name') != record['name']
                        or node.get('status', '').lower() != record['status'].lower()
                        or (node.get('conclusion') or '').lower() != (record.get('conclusion') or '').lower()
                        or node.get('startedAt') != record.get('startedAt')
                        or node.get('completedAt') != record.get('completedAt')
                        or suite['commit']['oid'] != head_sha
                        or suite['repository']['nameWithOwner'].casefold() != slug.casefold()):
                    raise ValueError('check execution changed during identity join')
                workflow_run = suite.get('workflowRun')
                workflow_id = ''
                if workflow_run is not None:
                    workflow = workflow_run['workflow']
                    workflow_id = workflow['id']
                    if not isinstance(workflow_id, str) or not workflow_id:
                        raise ValueError('invalid workflow identity')
                joined[identity] = {**record, 'workflowName': workflow_id}
        except (KeyError, TypeError, AttributeError, ValueError, json.JSONDecodeError):
            return [], 'required-check workflow identity inventory malformed or unstable'
    # REST pages are newest first; increasing IDs make same-second ordering
    # chronological for the existing conservative duplicate policy.
    return sorted([joined[item['node_id']] if item.get('__typename') == 'CheckRun' else item
                   for item in records], key=lambda item: item['id']), None


def required_checks_snapshot(
    root: Path,
    slug: str,
    base_branch: Any,
    base_sha: Any,
    head_sha: Any,
    hostname: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], str | None]:
    """Bind exact-head execution evidence to one stable required-check policy."""
    policy, error = _required_check_policy(root, slug, base_branch, base_sha, hostname)
    if error:
        return {}, [], error
    checks, error = _current_check_inventory(root, slug, head_sha, hostname)
    if error:
        return {}, [], error
    final_policy, error = _required_check_policy(root, slug, base_branch, base_sha, hostname)
    if error:
        return {}, [], error
    if final_policy.get("digest") != policy.get("digest"):
        return {}, [], "required-check policy changed during evidence collection"
    return policy, checks, None


def _check_timestamp(item: dict[str, Any]) -> str:
    for key in ("completedAt", "completed_at", "startedAt", "started_at", "createdAt", "created_at"):
        candidate = item.get(key)
        if isinstance(candidate, str) and candidate:
            return candidate
    return ""


def _check_lifecycle(item: dict[str, Any]) -> str:
    if item.get("__typename") == "CheckRun":
        status = item.get("status")
        if not isinstance(status, str) or not status:
            return ""
        normalized_status = status.lower()
        if normalized_status != "completed":
            return normalized_status
        conclusion = item.get("conclusion")
        return conclusion.lower() if isinstance(conclusion, str) and conclusion else normalized_status
    for key in ("state", "conclusion", "status"):
        candidate = item.get(key)
        if isinstance(candidate, str) and candidate:
            return candidate.lower()
    return ""


def _check_app_identity(item: dict[str, Any]) -> str:
    app = item.get("app")
    if isinstance(app, dict):
        for key in ("id", "slug", "name"):
            value = app.get(key)
            if value not in (None, ""):
                return str(value)
    if app not in (None, ""):
        return str(app)
    return ""


def _check_identity(item: dict[str, Any], index: int) -> tuple[str, ...]:
    """Return a safe dedupe key for one GitHub status/check entry.

    Status contexts are keyed by their context name. Check runs need their
    workflow/app identity as well as their display name; when GitHub omits
    that identity, keep the entry distinct instead of treating an unrelated
    same-named run as a rerun of the same check.
    """
    typename = str(item.get("__typename") or "")
    context = str(item.get("context") or "")
    name = str(item.get("name") or context or item.get("workflowName") or "unnamed check")
    if typename == "StatusContext" or context:
        return ("status", context or name)
    workflow = str(item.get("workflowName") or "")
    app = _check_app_identity(item)
    if typename == "CheckRun":
        if workflow or app:
            return ("check", name, workflow, app)
        return ("check-unidentified", name, str(index))
    if typename:
        return (typename, name, workflow, app)
    # Keep compatibility with small unit fixtures that model a check by name
    # only; real GitHub CheckRun objects carry __typename.
    return ("legacy", name)



def observed_checks_lane(pr: dict[str, Any], head_sha: str, *, attempt_order: bool = False) -> dict[str, Any]:
    checks = pr.get("statusCheckRollup")
    if not isinstance(checks, list) or not checks:
        return lane("blocked", "hosted PR reported no required check rollup for the current head", head_sha=head_sha, checks=[])
    if any(not isinstance(item, dict) for item in checks):
        return lane("blocked", "hosted PR reported malformed check evidence", head_sha=head_sha, checks=[])
    # GitHub retains every check-run for a commit in the PR rollup.  A rerun
    # after metadata repair therefore appears beside the failed predecessor
    # run, even though both refer to the same commit. Evaluate one current
    # context per name. Prefer the newest reported timestamp, but keep a
    # timestamp-less non-success duplicate ahead of an older completion so an
    # unproved rerun cannot be mistaken for a stale success. Timestamp-less
    # failures are handled the same way unless a later timestamped success in
    # the API order supersedes them.
    latest: dict[tuple[str, ...], tuple[int, int, str, int, dict[str, Any]]] = {}
    grouped: dict[tuple[str, ...], list[tuple[int, dict[str, Any]]]] = {}
    for index, item in enumerate(checks):
        if not isinstance(item, dict):
            continue
        grouped.setdefault(_check_identity(item, index), []).append((index, item))
    for identity, entries in grouped.items():
        for position, (index, item) in enumerate(entries):
            started = item.get('startedAt') if attempt_order and item.get('__typename') == 'CheckRun' else None
            timestamp = started if isinstance(started, str) and started else _check_timestamp(item)
            lifecycle = _check_lifecycle(item)
            later_timestamped_success = any(
                _check_lifecycle(later_item) in SUCCESS_CHECKS and _check_timestamp(later_item)
                for _later_index, later_item in entries[position + 1 :]
            )
            timestampless_failure = int(
                not timestamp
                and lifecycle in FAILED_CHECKS
                and not later_timestamped_success
            )
            # A non-success duplicate without timestamps is safer than an old
            # completed duplicate: it must not be hidden by a stale success.
            # The same applies to a timestamp-less failure until a later
            # timestamped success supersedes it.
            pending_without_timestamp = int(
                not timestamp and lifecycle not in SUCCESS_CHECKS | FAILED_CHECKS
            )
            rank = (timestampless_failure, pending_without_timestamp, timestamp, index)
            previous = latest.get(identity)
            if previous is None or rank >= previous[:4]:
                latest[identity] = (*rank, item)
    current_checks = [entry[4] for entry in latest.values()]
    failures: list[str] = []
    pending: list[str] = []
    for item in current_checks:
        name = str(item.get("name") or item.get("context") or item.get("workflowName") or "unnamed check")
        state = _check_lifecycle(item)
        if state in PENDING_CHECKS or not state:
            pending.append(name)
        elif state in FAILED_CHECKS:
            failures.append(name)
        elif state not in SUCCESS_CHECKS:
            pending.append(name)
    if failures:
        return lane("fail", f"required checks failed: {', '.join(failures)}", head_sha=head_sha, failures=failures, pending=pending)
    if pending:
        return lane("blocked", f"required checks are not complete: {', '.join(pending)}", head_sha=head_sha, failures=[], pending=pending)
    return lane("pass", f"{len(current_checks)} current check contexts passed for current PR head", head_sha=head_sha, checks=current_checks)


def _validated_required_check_policy(pr: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    policy = pr.get("requiredCheckPolicy")
    if not isinstance(policy, dict):
        return None, "authenticated required-check policy inventory is unavailable"
    digest = policy.get("digest")
    required = policy.get("required_checks")
    if (
        policy.get("schema_version") != REQUIRED_CHECK_POLICY_SCHEMA
        or policy.get("base_branch") != pr.get("baseRefName")
        or policy.get("base_sha") != pr.get("baseRefOid")
        or not isinstance(policy.get("repository"), str)
        or not isinstance(policy.get("sources"), list)
        or not policy["sources"]
        or not isinstance(required, list)
        or not isinstance(digest, str)
        or not SCOPE_DIGEST_RE.fullmatch(digest)
    ):
        return None, "authenticated required-check policy inventory is malformed"
    try:
        if any(
            not isinstance(item, dict)
            or set(item) != {"context", "app_id"}
            or _required_check_record(item.get("context"), item.get("app_id")) != item
            for item in required
        ):
            return None, "authenticated required-check identities are malformed"
        canonical = {key: value for key, value in policy.items() if key != "digest"}
        expected = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    except (TypeError, ValueError):
        return None, "authenticated required-check policy inventory is malformed"
    if expected != digest:
        return None, "authenticated required-check policy digest is invalid"
    return policy, None


def _check_matches_requirement(
    item: dict[str, Any],
    requirement: dict[str, Any],
    head_sha: str,
) -> bool:
    if item.get("head_sha") != head_sha:
        return False
    context = item.get("context") or item.get("name")
    if context != requirement["context"]:
        return False
    required_app = requirement["app_id"]
    if required_app is None:
        return True
    app = item.get("app")
    return (
        item.get("__typename") == "CheckRun"
        and isinstance(app, dict)
        and type(app.get("id")) is int
        and app["id"] == required_app
    )


def checks_lane(pr: dict[str, Any], head_sha: str) -> dict[str, Any]:
    """Require the provider's complete policy and retain every observed check gate."""
    policy, error = _validated_required_check_policy(pr)
    if error or policy is None:
        reason = pr.get("requiredCheckPolicyError")
        # Surface only diagnostics owned by the collector, never tool output.
        if reason in (
            "required-check policy requires an exact PR base branch and commit",
            "required-check branch policy inventory unavailable",
            "required-check ruleset inventory unavailable",
            "required workflow policy cannot be authenticated by the required-check lane",
            "required-check evidence requires an exact PR head",
            "current-head check-run inventory unavailable",
            "current-head status-context inventory unavailable",
            "current-head check inventory has duplicate node identities",
            "required-check workflow identity inventory unavailable",
            "required-check workflow identity inventory malformed or unstable",
            "required-check policy changed during evidence collection",
        ):
            error = reason
        return lane("blocked", error or "required-check policy is unavailable", head_sha=head_sha)
    evidence = pr.get("requiredCheckEvidence")
    if not isinstance(evidence, list) or any(not isinstance(item, dict) for item in evidence):
        return lane("blocked", "authenticated required-check execution inventory is unavailable",
                    head_sha=head_sha, policy_digest=policy["digest"])
    missing = [requirement["context"] + (f" (App {requirement['app_id']})" if requirement["app_id"] is not None else "") for requirement in policy["required_checks"]
               if not any(_check_matches_requirement(item, requirement, head_sha) for item in evidence)]
    if missing:
        return lane("blocked", "required checks are absent: " + ", ".join(missing),
                    head_sha=head_sha, policy_digest=policy["digest"], missing=missing)
    if not evidence or any(item.get("head_sha") != head_sha for item in evidence):
        return lane("blocked", "authenticated execution inventory lacks current-head evidence",
                    head_sha=head_sha, policy_digest=policy["digest"])
    inventory = observed_checks_lane({'statusCheckRollup': evidence}, head_sha, attempt_order=True)
    # Evaluate both snapshots. A later REST failure or queued rerun must not be
    # hidden by an earlier successful GraphQL rollup; neither can clear the other.
    observed = observed_checks_lane(pr, head_sha)
    if observed.get('details', {}).get('checks') != [] and (
        inventory['status'] == 'fail' or (inventory['status'] == 'blocked' and observed['status'] != 'fail')
    ):
        observed = inventory
    observed.setdefault("details", {}).update(policy_digest=policy["digest"],
        required_checks=policy["required_checks"], missing=[],
        unknown_required=any(_check_lifecycle(item) not in SUCCESS_CHECKS | PENDING_CHECKS | FAILED_CHECKS
                             for item in evidence))
    return observed


def phase_checks_lane(pr: dict[str, Any], head_sha: str, phase: str) -> dict[str, Any]:
    """Inspection observes CI failures; mutation and readiness retain their gates."""
    checks = checks_lane(pr, head_sha)
    if phase == "review_inspection":
        if pr.get("headRefOid") != head_sha or not re.fullmatch(r"[0-9a-f]{40}", head_sha):
            return lane("blocked", "review inspection requires the current hosted head", head_sha=head_sha)
        return lane("pass", "inspection only; CI outcome is observed, not accepted",
                    head_sha=head_sha, ci_status=checks["status"],
                    ci_evidence=checks["evidence"], ci_details=checks.get("details", {}),
                    acceptance_claims_proven=False)
    details = checks.get("details", {})
    rollup = pr.get("statusCheckRollup")
    known_states = isinstance(rollup, list) and bool(rollup) and all(
        isinstance(item, dict) and _check_lifecycle(item) in PENDING_CHECKS | SUCCESS_CHECKS | FAILED_CHECKS
        for item in rollup
    )
    if (phase == "review_reconciliation"
            and checks["status"] == "blocked" and details.get("pending")
            and details.get("failures") == [] and not details.get("missing")
            and not details.get("unknown_required") and known_states):
        return lane("pass", "review actions only; required CI is still pending",
                    head_sha=head_sha, ci_status=checks["status"],
                    ci_evidence=checks["evidence"], pending=details["pending"],
                    policy_digest=details.get("policy_digest"), missing=[],
                    acceptance_claims_proven=False)
    return checks


def _review_login(review: dict[str, Any]) -> str:
    author = review.get("author") or review.get("user")
    if isinstance(author, dict):
        return str(author.get("login") or "").removesuffix("[bot]")
    return ""


def _human_review_login(review: dict[str, Any]) -> str | None:
    """Require REST User metadata; account operation remains a host trust boundary."""
    user = review.get("user")
    if not isinstance(user, dict) or user.get("type") != "User":
        return None
    login = user.get("login")
    if (not isinstance(login, str)
            or len(login) > 39
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*(?:_[A-Za-z0-9]{3,8})?", login)
            or login.casefold() in BOT_REVIEWERS):
        return None
    return login


def _review_sha(review: dict[str, Any]) -> str | None:
    commit = review.get("commit")
    value = commit.get("oid") if isinstance(commit, dict) else commit
    value = value or review.get("commitOid") or review.get("commitOID") or review.get("commit_id")
    return str(value) if value else None


def _review_submitted_at(review: dict[str, Any]) -> str:
    return str(review.get("submittedAt") or "")


def _review_body(review: dict[str, Any]) -> str:
    return str(review.get("body") or "")


def _body_has_current_head(body: str, head_sha: str) -> bool:
    """Require a full or conventional abbreviated current-head binding."""
    if not head_sha:
        return False
    current_head = head_sha.lower()
    if current_head in body.lower():
        return True
    return any(current_head.startswith(token.lower()) for token in EXPLICIT_SHA_BINDING_RE.findall(body))


def _body_has_other_head(body: str, head_sha: str) -> bool:
    """Detect an explicit SHA binding that belongs to another commit."""
    current_head = head_sha.lower()
    return any(not current_head.startswith(token.lower()) for token in EXPLICIT_SHA_BINDING_RE.findall(body))


def _bot_review_has_explicit_no_findings(body: str, head_sha: str, *, full_head: bool = False) -> bool:
    """Parse a complete clearance statement, not a phrase in arbitrary prose."""
    statement = re.fullmatch(
        r"\s*No\s+(?:actionable\s+)?(?:comments?|findings?)"
        r"(?:\s+(?:were\s+)?(?:generated|found|posted))?\s+for\s+"
        r"(?:(?:commit|head|sha)\s*[:=]?\s*)?`?([0-9a-f]{7,64})`?[.!]?\s*",
        body, re.IGNORECASE,
    )
    return bool(statement and (head_sha.lower() == statement[1].lower() if full_head
                               else head_sha.lower().startswith(statement[1].lower())))


@lru_cache(maxsize=128)
def _reply_statement_in_pinned_runtime(body: str, disclosure_only: bool = False) -> str:
    """Use the existing offline parser runtime without changing the caller's Python."""
    script = Path(__file__).resolve()
    child = (
        "import importlib.util,json,sys; "
        "sys.path.insert(0,str(__import__('pathlib').Path(sys.argv[1]).resolve().parent)); "
        "spec=importlib.util.spec_from_file_location('readiness',sys.argv[1]); "
        "module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); "
        "print(json.dumps(module._coderabbit_reply_statement(sys.stdin.read(),allow_runtime=False,"
        "disclosure_only=sys.argv[2]=='1')))"
    )
    try:
        env = {key: value for key, value in os.environ.items()
               if key not in {"PYTHONPATH", "PYTHONHOME", "BASH_ENV", "ENV"}}
        env.update(UV_OFFLINE="1", UV_NO_CONFIG="1", UV_NO_PROJECT="1")
        with (
            tempfile.TemporaryDirectory(prefix="configs-review-parser-") as directory,
            subprocess.Popen(
                ["bash", str(script.with_name("codex-validation-python-uv.sh")), "-I", "-c", child, str(script),
                 "1" if disclosure_only else "0"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, env=env, cwd=directory, start_new_session=True,
            ) as process,
        ):
            try:
                stdout, _ = process.communicate(body, timeout=REPLY_TIMEOUT)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.communicate(timeout=5)
                return ""
            if process.returncode:
                return ""
        statement = json.loads(stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return ""
    return statement if isinstance(statement, str) else ""


def _coderabbit_reply_body(body: str) -> str:
    """Normalise only the two fixed provider header orders."""
    marker = "<!-- This is an auto-generated reply by CodeRabbit -->"
    if len(body) > 65536:
        return ""
    tip_prefix = "> [!TIP]\n> For best results, initiate chat on the files or code changes.\n\n"
    if body.startswith(tip_prefix + marker + "\n"):
        # The provider emits both header orders. Parse the same fixed layout
        # after moving only its complete leading tip behind the reply marker.
        body = marker + "\n\n" + tip_prefix + body[len(tip_prefix + marker):].lstrip("\n")
    return body if body.startswith(marker) else ""


def _completed_source_verdict(tokens: list[Any]) -> dict[str, str]:
    """Read the fixed completion clarification, never an attached failed action."""
    from markdown_it import MarkdownIt

    inline = [token.content for token in tokens if token.type == "inline"]
    words = ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
             "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen")
    if len(inline) != 6:
        return {}
    intro = re.fullmatch(
        r"`@[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})` Independent source inspection completed for "
        r"`([0-9a-f]{40}(?:[0-9a-f]{24})?)`\. The prior inspection covered all ("
        + "|".join(words) + r") changed files against base `([0-9a-f]{40}(?:[0-9a-f]{24})?)`\. "
        r"It reported no remaining findings\.", inline[0],
    )
    if not intro:
        return {}
    head, count, base = intro[1], str(words.index(intro[2]) + 1), intro[3]
    statement = f"No findings for {head}."
    expected = MarkdownIt("commonmark").parse(
        f"{inline[0]}\n\n{statement}\n\n"
        "The rate-limit notice applied to the separate automated review action. "
        "It did not invalidate the completed source inspection.\n\n"
        "The inspection did not execute repository code or tests. It does not establish "
        "hosted-check success, runtime correctness, or merge readiness.\n\n"
        "I did not repeat inspection, enable paid services, change source, approve, merge, "
        "or resolve threads.\n\n_You are interacting with an AI system._")
    def shape(items: list[Any]) -> list[tuple[Any, ...]]:
        return [(token.type, token.level, token.content, token.markup) for token in items]
    if shape(tokens) != shape(expected):
        return {}
    return {"base": base, "prior": head, "count": count, "source": "", "statement": statement}


def _source_inspection_disclosure(tokens: list[Any]) -> dict[str, str]:
    """Recognise complete two-file source reports, not arbitrary positive prose."""
    from markdown_it import MarkdownIt

    inline = [token.content for token in tokens if token.type == "inline"]
    if len(inline) < 2:
        return {}
    verdict = re.fullmatch(r"No findings for ([0-9a-f]{40}(?:[0-9a-f]{24})?)\.", inline[1])
    intro = re.fullmatch(
        r"(`@[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})`) Independent source inspection completed"
        r"(?: for the current PR diff\.|, as recorded in \[the referenced comment\]"
        r"\((https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[1-9][0-9]*"
        r"#issuecomment-[1-9][0-9]*)\)\. That inspection reported no remaining source findings\.)",
        inline[0],
    )
    bases = [match[1] for text in inline if (match := re.fullmatch(
        r"Inspected both changed files against base `([0-9a-f]{40}(?:[0-9a-f]{24})?)`\.", text))]
    if not verdict or not intro or len(bases) != 1:
        return {}
    head, base, source = verdict[1], bases[0], intro[2] or ""
    if source:
        evidence = """**Recorded inspection evidence**
- Confirmed that the PR head and local checkout matched the requested commit.
- Inspected both changed files against base `{base}`.
- Parsed the memory configuration and checked its values against JSC-511 and the checked-in schema.
- Inspected launcher override preservation, runtime isolation, hook trust checks, required-mode failures, canonical policy comparison, and Desktop-owned plugin preservation.
- Reported successful hosted results for `config-governance` and `ci/circleci: test`.

**Evidence limits**
The inspection did not independently execute repository checks or the Desktop launcher. Workstation runtime agreement and required-mode execution remain author-provided evidence. Memory model availability and execution quality were not independently tested. These are validation limits, not identified source defects.

This clarification read only the referenced comment. I did not repeat inspection, enable services, change source, approve, merge, or resolve threads."""
    else:
        evidence = """**Inspection evidence**
- Confirmed the PR head and local checkout match the requested commit.
- Inspected both changed files against base `{base}`.
- Parsed `codex/config.toml`. The memory values match JSC-511 and the checked-in schema.
- Verified that the launcher change preserves `CODEX_VALIDATION_CODEX_BIN`, runtime isolation, hook trust checks, and required-mode failures.
- Inspected the existing canonical policy comparison and Desktop-owned plugin preservation code.

**Validation limits**
I did not execute repository code or the Desktop launcher. Actual workstation runtime agreement and required-mode execution remain author-provided evidence. Memory model availability and execution quality were not independently tested.

Current hosted results report success for `config-governance` and `ci/circleci: test`. These results supersede the earlier reported timeout and failure.

I did not change source, enable services, approve, merge, or resolve threads.

[full_review]"""
    statement = f"No findings for {head}."
    expected = MarkdownIt("commonmark").parse(
        f"{inline[0]}\n\n{statement}\n\n{evidence.format(base=base)}\n\n"
        "_You are interacting with an AI system._")
    def shape(items: list[Any]) -> list[tuple[Any, ...]]:
        return [(token.type, token.level, token.content, token.markup) for token in items]
    if shape(tokens) != shape(expected):
        return {}
    # This envelope covers both files at this exact head; it reports no prior repair revision.
    return {"base": base, "prior": head, "count": "2", "source": source, "statement": statement,
            "paths": "codex/config.toml,codex/scripts/validate-codex-hooks.sh"}


def _coderabbit_reply_statement(body: str, *, allow_runtime: bool = True, disclosure_only: bool = False) -> str:
    """Extract only the outer verdict from the known authenticated reply layout."""
    marker = "<!-- This is an auto-generated reply by CodeRabbit -->"
    body = _coderabbit_reply_body(body)
    if not body:
        return ""
    if allow_runtime:
        return _reply_statement_in_pinned_runtime(body, True) if disclosure_only else _reply_statement_in_pinned_runtime(body)
    if not sys.flags.isolated:
        return ""
    try:
        from importlib.metadata import distribution

        import markdown_it
        from markdown_it import MarkdownIt
        package = distribution("markdown-it-py")
        if (package.version != "4.2.0"
            or Path(markdown_it.__file__).resolve() != Path(str(package.locate_file("markdown_it/__init__.py"))).resolve()):
            return ""
    except (ImportError, ValueError, OSError):
        return ""
    tokens = MarkdownIt("commonmark").parse(body)
    # Only standalone statuses and identified tool output report service state;
    # reviewed code, inline literals and explanatory prose are not executions.
    output_follows = False
    for token in tokens:
        visible = "".join("\n" if child.type in {"softbreak", "hardbreak"} else child.content
                          for child in token.children or [] if child.type != "code_inline")
        if token.type in {"fence", "code_block"}:
            if (output_follows or token.info.strip().lower() in {"output", "stdout", "stderr"}) and (
                _bot_review_has_blocked_response(token.content, parsed_reply=True)
                or BOT_OUTPUT_DIAGNOSTIC_RE.search(token.content)
            ):
                return ""
            output_follows = False
        elif token.type == "inline":
            if BOT_REPLY_BLOCKED_RE.fullmatch(visible):
                return ""
            output_follows = bool(re.fullmatch(
                r"\s*(?:(?:tool\s+)?output\s*:|length\s+of\s+output\s*:\s*\d+)\s*",
                visible, re.IGNORECASE,
            ))
        elif token.type in {"html_block", "hr", "blockquote_open", "blockquote_close"}:
            output_follows = False
    if not tokens or tokens[0].type != "html_block" or tokens[0].content.strip() != marker:
        return ""
    cursor = 1
    tip = tokens[cursor:cursor + 5]
    if tip and tip[0].type == "blockquote_open":
        if ([token.type for token in tip] != ["blockquote_open", "paragraph_open", "inline",
                                              "paragraph_close", "blockquote_close"]
            or tip[2].content != "[!TIP]\nFor best results, initiate chat on the files or code changes."):
            return ""
        cursor += 5
    paragraph = [("paragraph_open", 0), ("inline", 1), ("paragraph_close", 0)]
    mention = r"(?:`@[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})`|@[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))"
    mention_seen = False
    if ([(token.type, token.level) for token in tokens[cursor:cursor + 3]] == paragraph
        and re.fullmatch(mention, tokens[cursor + 1].content)):
        cursor += 3
        mention_seen = True
    analysis_known = False
    analysis_section_seen = False
    analysis_item_seen = False
    diff_traces: list[tuple[str, str]] = []
    if cursor < len(tokens) and tokens[cursor].type == "html_block":
        if tokens[cursor].content.strip() != "<details>\n<summary>🧩 Analysis chain</summary>":
            return ""
        analysis_section_seen = True
        analysis_known = True
        cursor += 1
        analysis_start = cursor
        while cursor < len(tokens) and tokens[cursor].type != "html_block":
            if any(child.type == "html_inline" for child in tokens[cursor].children or []):
                return ""
            cursor += 1
        # Fenced code is a single Markdown token, so a quoted closing tag
        # cannot terminate this section. Unknown/nested raw HTML fails closed.
        if (cursor == len(tokens) or tokens[cursor].level != 0
            or tokens[cursor].content.strip() != "</details>"):
            return ""
        # Discard only known provider tool traces, not arbitrary reviewer prose.
        # Unknown narrative requires inspection; a positive outer tail cannot
        # contradict or hide findings in this disclosure.
        previous_inline = ""
        for token in tokens[analysis_start:cursor]:
            if token.type == "inline":
                previous_inline = token.content
                retry_message = re.fullmatch(
                    r"(?:Rate limit exceeded|HTTP 401 Unauthorized) errors are retried"
                    r"(?: for [0-9a-f]{40}(?:[0-9a-f]{24})?)?", previous_inline,
                )
                if (previous_inline not in {"🏁 Script executed:", "Inspected exact candidate."}
                    and not re.fullmatch(r"Length of output: [0-9]+", previous_inline)
                    and retry_message is None):
                    analysis_known = False
                elif previous_inline == "Inspected exact candidate." or retry_message is not None:
                    analysis_item_seen = True
            elif token.type == "fence":
                # Only observed command traces may be discarded as decoration.
                # A language label alone must not hide narrative or findings.
                known_trace = re.fullmatch(
                    r"(?:git diff (?P<base>[0-9a-f]{40}(?:[0-9a-f]{24})?) (?P<head>[0-9a-f]{40}(?:[0-9a-f]{24})?) --stat"
                    r"|gh api repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/issues/comments/[1-9][0-9]*"
                    r"|printf '</details>')", token.content.removesuffix("\n"),
                )
                if (previous_inline != "🏁 Script executed:" or token.info not in {"shell", "bash", "sh"}
                    or known_trace is None):
                    analysis_known = False
                else:
                    analysis_item_seen = True
                if known_trace is not None and known_trace["base"]:
                    diff_traces.append((known_trace["base"], known_trace["head"]))
                previous_inline = ""
            elif token.type not in {"paragraph_open", "paragraph_close", "hr"}:
                analysis_known = False
        cursor += 1
    tail = tokens[cursor:]
    # CodeRabbit also places the decorative mention after analysis.
    if ([(token.type, token.level) for token in tail[:3]] == paragraph
        and re.fullmatch(mention, tail[1].content)):
        if mention_seen:
            return ""
        tail = tail[3:]
        mention_seen = True
    # CodeRabbit can place the fixed learning disclosure immediately before
    # the AI footer. Move only that exact four-token envelope behind the
    # footer, where the same strict metadata validation below applies.
    if (len(tail) >= 10
        and [(token.type, token.level) for token in tail[-7:-4]] == [
            ("hr", 0), ("html_block", 0), ("fence", 0)]
        and tail[-4].type == "html_block"
        and tail[-6].content.strip() == "<details>\n<summary>🧠 Learnings used</summary>"
        and tail[-4].content.strip() == "</details>"
        and [(token.type, token.level) for token in tail[-3:]] == paragraph
        and tail[-2].content == "_You are interacting with an AI system._"):
        tail = tail[:-7] + tail[-3:] + tail[-7:-3]
    metadata = (
        r"Learnt from: [A-Za-z0-9][A-Za-z0-9-]{0,38}\n"
        r"URL: https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[1-9][0-9]*\n\n"
        r"Timestamp: [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z\n"
        r"Learning: [^\r\n]+\n"
    )
    used = tail[-4:]
    if (len(used) == 4 and used[1].type == "html_block"
        and used[1].content.strip() == "<details>\n<summary>🧠 Learnings used</summary>"):
        if ([(token.type, token.level) for token in used] != [
            ("hr", 0), ("html_block", 0), ("fence", 0), ("html_block", 0),
        ] or used[2].info or used[3].content.strip() != "</details>"
            or not re.fullmatch(metadata, used[2].content)):
            return ""
        tail = tail[:-4]
    # Both fixed learning disclosures decorate the outer verdict. Validate
    # them before either static-inspection layout is matched.
    appendix = tail[-9:]
    if (len(appendix) == 9 and appendix[1].type == "html_block"
        and appendix[1].content.strip() == "<details>\n<summary>✏️ Learnings added</summary>"):
        note = (
            "Note: Learnings are effective only in the context of similar code segments. "
            "To apply general coding guidelines, please configure "
            "[review instructions](https://docs.coderabbit.ai/guides/review-instructions). "
            "You can manage existing learnings in the [app](https://app.coderabbit.ai/learnings)."
        )
        if ([(token.type, token.level) for token in appendix] != [
            ("hr", 0), ("html_block", 0), ("fence", 0),
            ("blockquote_open", 0), ("paragraph_open", 1), ("inline", 2),
            ("paragraph_close", 1), ("blockquote_close", 0), ("html_block", 0),
        ] or appendix[2].info or appendix[5].content != note
            or appendix[8].content.strip() != "</details>"
            or not re.fullmatch(metadata, appendix[2].content)):
            return ""
        tail = tail[:-9]
    source_disclosure = _source_inspection_disclosure(tail) or _completed_source_verdict(tail)
    if analysis_section_seen and (not analysis_known or not analysis_item_seen):
        return ""
    disclosure = {key: value for key, value in source_disclosure.items() if key != "statement"}
    if source_disclosure:
        tail = MarkdownIt("commonmark").parse(
            source_disclosure["statement"] + "\n\n_You are interacting with an AI system._")
    if (len(tail) == 18
        and [(token.type, token.level) for token in tail] == paragraph * 6
        and re.fullmatch(
            mention + r" Independent static inspection completed, as reported in "
            r"\[the referenced comment\]\(https://github\.com/[A-Za-z0-9_.-]+/"
            r"[A-Za-z0-9_.-]+/pull/[1-9][0-9]*#issuecomment-[1-9][0-9]*\)\. "
            r"No actionable findings remained from that inspection\.", tail[1].content,
        )):
        if (not re.fullmatch(
            r"The completed inspection covered all [1-9][0-9]* changed files against base "
            r"`[0-9a-f]{40}(?:[0-9a-f]{24})?`, including repairs since "
            r"`[0-9a-f]{40}(?:[0-9a-f]{24})?`\. `git diff --check` passed\. "
            r"GitHub reported the requested head and base at the end of inspection\.", tail[7].content,
        ) or tail[10].content != (
            "**Evidence limits:** I did not execute repository code or tests. The verdict does not "
            "establish hosted-check success, runtime correctness, or merge readiness."
        ) or tail[13].content != (
            "This reply clarifies the prior evidence. I did not repeat inspection, enable paid services, "
            "change source, approve, merge, or resolve threads."
        )):
            return ""
        revisions = re.findall(r"`([0-9a-f]{40}(?:[0-9a-f]{24})?)`", tail[7].content)
        count = re.search(r"all ([1-9][0-9]*) changed files", tail[7].content)
        link = re.search(r"\[the referenced comment\]\(([^)]+)\)", tail[1].content)
        if count is None or link is None:
            return ""
        disclosure = {"base": revisions[0], "prior": revisions[1], "count": count[1], "source": link[1]}
        tail = tail[3:6] + tail[-3:]
    # Admit the complete known static-inspection disclosure, not a positive
    # substring embedded in an arbitrary report. The outer verdict remains
    # the only clearance evidence; CI, identity and freshness stay upstream.
    if (len(tail) == 18
        and [(token.type, token.level) for token in tail] == paragraph * 6):
        provenance = (
            r"I completed independent static inspection of all [1-9][0-9]* changed files "
            r"against base `[0-9a-f]{40}(?:[0-9a-f]{24})?`\. "
            r"I also inspected the repairs since `[0-9a-f]{40}(?:[0-9a-f]{24})?`\."
        )
        coverage = (
            "The inspection covered duplication detection, reserved-definition counts, baseline handling, "
            "fixture isolation, validation wiring, inspection receipts, authenticated request reuse, and "
            "Codex completion evidence. `git diff --check` passed. GitHub still reported the requested "
            "head and base after inspection."
        )
        limits = (
            "**Inspection limits:** I did not execute repository code or tests. This verdict does not "
            "establish hosted-check success, runtime correctness, or merge readiness."
        )
        authority = (
            "I used read-only inspection. I did not enable paid services, change source, approve, merge, "
            "or resolve threads."
        )
        if (not re.fullmatch(provenance, tail[4].content)
            or tail[7].content != coverage or tail[10].content != limits
            or tail[13].content != authority):
            return ""
        revisions = re.findall(r"`([0-9a-f]{40}(?:[0-9a-f]{24})?)`", tail[4].content)
        count = re.search(r"all ([1-9][0-9]*) changed files", tail[4].content)
        if count is None:
            return ""
        disclosure = {"base": revisions[0], "prior": revisions[1], "count": count[1], "source": ""}
        tail = tail[:3] + tail[-3:]
    # A fixed metadata-verification disclosure explains the completed repair;
    # only the separate outer verdict supplies clearance. Unknown prose fails closed.
    if (len(tail) == 12
        and [(token.type, token.level) for token in tail[:12]] == paragraph * 4):
        verification = re.fullmatch(
            r"The completed review’s only actionable finding concerned installed-wheel validation evidence\. "
            r"\[The subsequent verification\]\((https://github\.com/[A-Za-z0-9_.-]+/"
            r"[A-Za-z0-9_.-]+/pull/[1-9][0-9]*#discussion_r[1-9][0-9]*)\) "
            r"confirmed that the published PR body satisfied that finding\.", tail[4].content,
        )
        if (verification is None or not analysis_section_seen or tail[7].content != (
            "This clarifies the existing inspection record. It does not grant approval or establish merge readiness."
        )):
            return ""
        disclosure = {"verification": verification[1]}
        # Learning appendices were validated above; retain the complete footer.
        tail = tail[:3] + tail[9:]
    if not analysis_section_seen and not disclosure and not mention_seen:
        return ""
    # CodeRabbit adds a plain or inline-code mention as its own paragraph or
    # before the outer verdict. It is decoration, never verdict evidence.
    if ([(token.type, token.level) for token in tail] != [
        ("paragraph_open", 0), ("inline", 1), ("paragraph_close", 0),
        ("paragraph_open", 0), ("inline", 1), ("paragraph_close", 0),
    ] or tail[4].content != "_You are interacting with an AI system._"):
        return ""
    if mention_seen and re.match(r"^" + mention + r"\s+", tail[1].content):
        return ""
    statement = re.sub(r"^" + mention + r"\s+", "", tail[1].content)
    if any(base != disclosure.get("base") or not _bot_review_has_explicit_no_findings(statement, head, full_head=True)
           for base, head in diff_traces):
        return ""
    if disclosure_only:
        return json.dumps({**disclosure, "statement": statement} if disclosure else {})
    return statement


_CODEX_ABOUT_GITHUB_FOOTER = (
    '<details> <summary>ℹ️ About Codex in GitHub</summary> <br/> '
    '[Your team has set up Codex to review pull requests in this repo]'
    '(https://chatgpt.com/codex/cloud/settings/general). Reviews are triggered when you '
    '- Open a pull request for review - Mark a draft as ready - Comment "@codex review". '
    'If Codex has suggestions, it will comment; otherwise it will react with 👍. '
    'Codex can also answer questions or update the PR. Try commenting '
    '"@codex address that feedback". </details>'
)
_CODEX_VIEW_TASK_FOOTER_RE = re.compile(
    r"\[View task →\]\(https://chatgpt\.com/s/cd_[A-Za-z0-9]+\)"
)


def _codex_clearance_footer(remainder: str) -> bool:
    """True when trailing text is only Codex's known auto-appended footer."""
    normalized = " ".join(remainder.split())
    if not normalized:
        return True
    view_task = _CODEX_VIEW_TASK_FOOTER_RE.fullmatch(normalized)
    if view_task:
        return True
    if normalized == _CODEX_ABOUT_GITHUB_FOOTER:
        return True
    combined = re.fullmatch(
        r"(\[View task →\]\(https://chatgpt\.com/s/cd_[A-Za-z0-9]+\)) (.+)",
        normalized,
    )
    return bool(combined and combined[2] == _CODEX_ABOUT_GITHUB_FOOTER)


def _codex_receipt_body(body: str) -> str:
    """Remove one exact provider receipt prefix, retaining all report content."""
    stripped = re.sub(r"\A<!-- codex-review-receipt:v1 -->\r?\n(?:[ \t]*\r?\n)+", "", body, count=1)
    return stripped if "<!-- codex-review-receipt:" not in stripped else body


def _codex_no_findings_reply(body: str, head_sha: str | None) -> bool:
    """Accept exact full-sha clearance plus optional known Codex footer only."""
    lines = _codex_receipt_body(body).splitlines()
    first_index = next((index for index, line in enumerate(lines) if line.strip()), None)
    if first_index is None:
        return False
    statement = re.fullmatch(
        r"No findings for ([0-9a-f]{40}|[0-9a-f]{64})\.",
        lines[first_index].strip(),
    )
    if not statement:
        return False
    sha = statement[1].lower()
    if head_sha is None:
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", sha):
            return False
    elif sha != head_sha.lower():
        return False
    return _codex_clearance_footer("\n".join(lines[first_index + 1 :]))


def _codex_no_findings_report(body: str, head_sha: str | None) -> bool:
    """Recognise the complete fixed positive layout, optionally head-bound."""
    report = re.fullmatch(
        r"Codex Review: Didn't find any major issues\. "
        r"(?:Already looking forward to the next diff\.|Keep them coming!|"
        r"More of your lovely PRs please\.|Chef's kiss\.|You're on a roll\.|:tada:|Delightful!|"
        r"Breezy!|Swish!|Hooray!|Bravo\.|Keep it up!|Nice work!|:rocket:|:\+1:|Can't wait for the next one!|Another round soon, please!)"
        r"\s+\*\*Reviewed commit:\*\* `([0-9a-f]{7,40}|[0-9a-f]{64})`\s+(.+?)\s*",
        _codex_receipt_body(body), re.DOTALL,
    )
    if not report or (head_sha is not None and not head_sha.lower().startswith(report[1])):
        return False
    return " ".join(report[2].split()) == _CODEX_ABOUT_GITHUB_FOOTER


def _codex_positive_clearance(body: str, head_sha: str | None) -> bool:
    """Codex-only clearance layouts: fixed report or exact statement + footer."""
    body = body.removeprefix("<!-- codex-review-receipt:v1 -->\n\n")
    return _codex_no_findings_report(body, head_sha) or _codex_no_findings_reply(body, head_sha)


def _unique_provider_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate fields in versioned provider metadata."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate provider metadata field")
        result[key] = value
    return result


def _codex_state_summary_body(text: str, *, corroborated_security: bool = False) -> tuple[str, str | None]:
    """Validate the observed state envelope before using the existing parser."""
    marker = "<!-- codex-pull-request-review-summary -->"
    match = re.fullmatch(re.escape(marker) + r" <!-- codex-review-state:v1 (.*?) --> (.+)", text)
    if not match:
        return text, None
    try:
        state = json.loads(match[1], object_pairs_hook=_unique_provider_object)
        security = re.search(r"<!-- codex-security-review:v1 (.*?) -->", match[2])
        security_metadata = json.loads(security[1], object_pairs_hook=_unique_provider_object) if security else None
    except (ValueError, TypeError, RecursionError):
        return "", None
    if not isinstance(state, dict) or set(state) != {"code_review", "security_review"}:
        return "", None
    code_only = state["security_review"] == dict.fromkeys(("commit_sha", "has_any_findings", "has_unresolved_findings", "status"))
    for name, label in (("code_review", "📝 **Code Review**"), ("security_review", "🔒 **Security Review**")):
        item = state[name]
        if name == "security_review" and code_only:
            if "🔒 **Security Review**" in match[2] or security_metadata is not None:
                return "", None
            continue
        unknown_security = (name == "security_review" and corroborated_security
                            and item.get("has_any_findings") is None
                            and item.get("has_unresolved_findings") is None) if isinstance(item, dict) else False
        if (not isinstance(item, dict) or set(item) != {
            "commit_sha", "has_any_findings", "has_unresolved_findings", "status"
        } or not isinstance(item["commit_sha"], str) or not SHA_RE.fullmatch(item["commit_sha"])
            or item["status"] != "completed" or (not unknown_security and (
                item["has_any_findings"] is not False or item["has_unresolved_findings"] is not False))):
            return "", None
        row = re.search(re.escape("| " + label) + r' \| ✅ \*\*Completed\*\* <relative-time datetime="[^"]+">[^<]+</relative-time> \| `([0-9a-f]{7,40}|[0-9a-f]{64})` \|', match[2])
        if not row or not item["commit_sha"].startswith(row[1]):
            return "", None
    head = state["code_review"]["commit_sha"]
    if not code_only and (state["security_review"]["commit_sha"] != head
        or not isinstance(security_metadata, dict) or security_metadata.get("headSha") != head):
        return "", None
    return marker + " " + match[2], head


def _codex_security_findings(body: str) -> str:
    """Describe security evidence after complete layout validation, not clearance."""
    match = re.search(r"<!-- codex-review-state:v1 (.*?) -->", " ".join(body.split()))
    if match is None:
        return "not_reported"  # Legacy activity/reactions prove only code review.
    state = json.loads(match[1], object_pairs_hook=_unique_provider_object)["security_review"]
    if state["status"] is None:
        return "not_reported"
    return "no_findings" if state["has_any_findings"] is False else "unknown"


def _codex_code_completion(body: str, *, corroborated_security: bool = False) -> tuple[str, str] | None:
    """Parse complete provider layouts; security activity never clears code."""
    text = " ".join(body.split())
    collapsed = "<details> <summary><strong>Codex Review Summary</strong>: ✅ Completed</summary>"
    if collapsed in text:
        if text.count(collapsed) != 1 or not text.endswith(" </details>"):
            return None
        text = text.removesuffix(" </details>").replace(collapsed, "## Codex Review Summary", 1)
    text, state_head = _codex_state_summary_body(text, corroborated_security=corroborated_security)
    security = re.search(r"<!-- codex-security-review:v1 (.*?) -->", text)
    if security:
        if not text.startswith("<!-- codex-pull-request-review-summary --> " + security[0] + " "):
            return None
        try:
            metadata = json.loads(security[1], object_pairs_hook=_unique_provider_object)
        except (ValueError, TypeError, RecursionError):
            return None
        if (not isinstance(metadata, dict) or set(metadata) != {
            "blockingSeverityThreshold", "headSha", "mergeGateEnabled",
            "pullRequestNumber", "repository", "status"
        } or not isinstance(metadata["blockingSeverityThreshold"], str)
            or metadata["blockingSeverityThreshold"] not in {"P0", "P1", "P2", "P3"}
            or not isinstance(metadata["headSha"], str) or not SHA_RE.fullmatch(metadata["headSha"])
            or metadata["mergeGateEnabled"] is not False or metadata["status"] != "completed"
            or type(metadata["pullRequestNumber"]) is not int or metadata["pullRequestNumber"] < 1
            or not isinstance(metadata["repository"], str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", metadata["repository"])):
            return None
        row = re.search(
            r'\| 🔒 \*\*Security Review\*\* \| ✅ \*\*Completed\*\* <relative-time datetime="([^"]+)">\1</relative-time> \| `([0-9a-f]{7,40}|[0-9a-f]{64})` \| (?:Manual request|Automatic|PR opened|New commits|Draft marked ready) \| ', text
        )
        if (not row or _codex_event_time(row[1]) is None or not metadata["headSha"].startswith(row[2])
            or not text[row.end():].startswith("<details> ")):
            return None
        text = text[:row.start()] + text[row.end():]
        text = text.replace(security[0] + " ", "", 1)
    report = re.fullmatch(
        r"<!-- codex-pull-request-review-summary --> "
        r"## Codex Review Summary This comment shows the latest Codex review activity on this pull request\. "
        r"\| Review \| Status \| Commit \| Review trigger \| \| --- \| --- \| --- \| --- \| "
        r"\| 📝 \*\*Code Review\*\* \| ✅ \*\*Completed\*\* <relative-time datetime=\"([^\"]+)\">\1</relative-time> \| `([0-9a-f]{7,40}|[0-9a-f]{64})` \| (?:Manual request|Automatic|PR opened|New commits|Draft marked ready) \| "
        r"<details> <summary>ℹ️ About Codex in GitHub</summary> <br/> "
        r"\[Your team has set up Codex to review pull requests in this repo\]\(https://chatgpt\.com/codex/cloud/settings/general\)\. Reviews are triggered when you "
        r'- Open a pull request for review - Mark a draft as ready - Comment "@codex review" or "@codex security review"\. '
        r"Codex reacts with 👀 while any review is running, comments if it has suggestions, and reacts with 👍 once all reviews finish with no findings\. </details>",
        text,
    )
    if report and _codex_event_time(report[1]) is not None:
        return state_head or report[2], report[1]
    return None


def _codex_event_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", value):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _codex_service_user(entry: dict[str, Any]) -> bool:
    user = entry.get("user")
    # GitHub reactions serialise this app actor as User, comments as Bot.
    return (isinstance(user, dict) and user.get("login") == "chatgpt-codex-connector[bot]"
            and user.get("type") in {"Bot", "User"}
            and type(user.get("id")) is int and user["id"] > 0)


def _codex_reactions(root: Path, slug: str, number: int) -> tuple[list[dict[str, Any]], str | None]:
    # This supported provider layout reacts on the PR's issue body, not the
    # summary comment. Require the temporal/actor join; a bare PR thumb fails.
    result = run_command(["gh", "api", f"repos/{slug}/issues/{number}/reactions", "--paginate", "--slurp"], root, check=False)
    if result.returncode:
        return [], "Codex reaction inventory is unavailable"
    try:
        pages = json.loads(result.stdout)
        if not isinstance(pages, list) or not pages or any(not isinstance(page, list) for page in pages):
            raise ValueError("expected paginated reaction arrays")
        reactions = [entry for page in pages for entry in page]
        if any(not isinstance(entry, dict) or type(entry.get("id")) is not int or entry["id"] <= 0
               or not isinstance(entry.get("user"), dict) or not isinstance(entry.get("content"), str)
               or _codex_event_time(entry.get("created_at")) is None for entry in reactions):
            raise ValueError("invalid reaction identity or time")
        return reactions, None
    except (ValueError, TypeError):
        return [], "Codex reaction inventory is malformed"


def _codex_matching_reaction(entry: dict[str, Any], completed: str, reactions: list[dict[str, Any]]) -> dict[str, Any] | None:
    completion_time = _codex_event_time(completed)
    created = _codex_event_time(entry.get("created_at"))
    updated = _codex_event_time(entry.get("updated_at"))
    if completion_time is None or created is None or created > completion_time or updated is None or not -1 <= (updated - completion_time).total_seconds() <= 3:
        return None
    for reaction in reactions:
        reacted = _codex_event_time(reaction.get("created_at"))
        if (_codex_service_user(reaction) and reaction["user"]["id"] == entry["user"]["id"]
            and reaction.get("content") == "+1"
            and reacted is not None and 0 <= (reacted - completion_time).total_seconds() <= 300):
            return reaction
    return None


def _codex_completion_snapshot(root: Path, pr: dict[str, Any], inline: list[dict[str, Any]], entries: list[dict[str, Any]], reactions: list[dict[str, Any]] | None, slug: str) -> tuple[bool, str | None]:
    fresh, error = gh_pr(root, number=pr["number"])
    if error or fresh is None or any(fresh.get(key) != pr.get(key) for key in (
        "number", "url", "state", "isDraft", "headRefName", "headRefOid",
        "baseRefName", "baseRefOid", "reviewDecision", "reviews",
    )):
        return False, "Codex completion PR identity, head or review inventory changed during verification"
    fresh_entries, error = issue_comments(root, pr["number"])
    if error or fresh_entries != entries:
        return False, "Codex completion comment inventory changed during verification"
    fresh_inline, error = review_comments(root, pr["number"])
    if error or fresh_inline != inline:
        return False, "Codex completion finding inventory changed during verification"
    if reactions is None:
        return True, None
    fresh_reactions, error = _codex_reactions(root, slug, pr["number"])
    if error:
        return False, None  # Unavailable optional evidence cannot clear anything.
    if fresh_reactions != reactions:
        return False, "Codex completion reaction inventory changed during verification"
    return True, None


def _codex_receipts_unedited(root: Path, receipts: list[dict[str, Any]]) -> bool:
    """Verify exact REST sources against GitHub's independent edit inventory."""
    ids = [entry.get("node_id") for entry in receipts]
    if (len(ids) != 2 or any(not isinstance(value, str) or not value or len(value) > 256 for value in ids)
        or len(set(ids)) != 2):
        return False
    query = ("query($ids:[ID!]!){nodes(ids:$ids){... on IssueComment{"
             "id url body createdAt updatedAt lastEditedAt includesCreatedEdit "
             "userContentEdits(first:1){totalCount}}}}")
    command = ["gh", "api", "graphql", "-f", "query=" + query]
    for node_id in ids:
        command.extend(["-f", "ids[]=" + node_id])
    result = run_command(command, root, check=False)
    if result.returncode:
        return False
    try:
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict) or payload.get("errors"):
            return False
        nodes = payload["data"]["nodes"]
        if not isinstance(nodes, list) or len(nodes) != len(receipts):
            return False
        for node, receipt in zip(nodes, receipts, strict=True):
            if (not isinstance(node, dict) or not {"id", "url", "body", "createdAt", "updatedAt",
                                                   "lastEditedAt", "includesCreatedEdit", "userContentEdits"} <= set(node)
                or node["id"] != receipt.get("node_id") or node["url"] != receipt.get("html_url")
                or node["body"] != receipt.get("body") or node["createdAt"] != receipt.get("created_at")
                or node["updatedAt"] != receipt.get("updated_at") or node["lastEditedAt"] is not None
                or node["includesCreatedEdit"] is not False or not isinstance(node["userContentEdits"], dict)
                or type(node["userContentEdits"].get("totalCount")) is not int
                or node["userContentEdits"]["totalCount"] != 0):
                return False
        return True
    except (ValueError, TypeError, KeyError):
        return False


def _codex_consistent_author(entry: dict[str, Any]) -> bool:
    """Reject a second, conflicting actor representation on REST evidence."""
    author, user = entry.get("author"), entry.get("user")
    return author is None or (isinstance(author, dict) and isinstance(user, dict)
                              and type(author.get("id")) is int
                              and all(author.get(key) == user.get(key) for key in ("id", "login", "type")))


def _codex_correlated_receipts(root: Path, pr: dict[str, Any], head: str, summary: dict[str, Any],
                               entries: list[dict[str, Any]]) -> dict[str, str] | None:
    """Corroborate unknown security flags with correlated native provider reports."""
    body = _codex_receipt_body(_review_body(summary))
    completion = _codex_code_completion(body, corroborated_security=True)
    marker = re.search(r"<!-- codex-review-state:v1 ([^\n]*?) -->", body)
    security_row = re.search(r'\| 🔒 \*\*Security Review\*\* \| ✅ \*\*Completed\*\* <relative-time datetime="([^"]+)">\1</relative-time>', body)
    app = summary.get("performed_via_github_app")
    if (completion is None or marker is None or security_row is None
        or not _codex_service_user(summary) or not _codex_consistent_author(summary)
        or summary["user"].get("type") != "Bot"
        or not isinstance(app, dict) or type(app.get("id")) is not int or app.get("id") != 1144995
        or app.get("slug") != "chatgpt-codex-connector"):
        return None
    try:
        state = json.loads(marker[1], object_pairs_hook=_unique_provider_object)
        security = state["security_review"]
        if security["has_any_findings"] is not None or security["has_unresolved_findings"] is not None:
            return None
    except (ValueError, TypeError, KeyError, RecursionError):
        return None
    code_time = _codex_event_time(completion[1])
    security_time = _codex_event_time(security_row[1])
    created = _codex_event_time(summary.get("created_at"))
    updated = _codex_event_time(summary.get("updated_at"))
    if (not code_time or not security_time or not created or not updated or created > code_time
        or security_time <= code_time or not -1 <= (updated - security_time).total_seconds() <= 3):
        return None
    prefix = str(pr.get("url") or "") + "#issuecomment-"
    matches: dict[str, list[dict[str, Any]]] = {"code": [], "security": []}
    for entry in entries:
        if not isinstance(entry, dict):
            return None
        # The validated summary is expected to be updated near security
        # completion. No other comment is exempt from ambiguity checks.
        if entry is summary:
            continue
        receipt_created = _codex_event_time(entry.get("created_at"))
        receipt_updated = _codex_event_time(entry.get("updated_at"))
        if receipt_created is None or receipt_updated is None or receipt_updated < receipt_created:
            return None
        for name, completed_at in (("code", code_time), ("security", security_time)):
            if any(-3 <= (event - completed_at).total_seconds() <= 3
                   for event in (receipt_created, receipt_updated)):
                matches[name].append(entry)
    if any(len(group) != 1 for group in matches.values()) or matches["code"][0] is matches["security"][0]:
        return None
    for name in ("code", "security"):
        entry = matches[name][0]
        provider = entry.get("performed_via_github_app")
        if (not _codex_service_user(entry) or not _codex_consistent_author(entry)
            or entry["user"].get("type") != "Bot"
            or entry["user"]["id"] != summary["user"]["id"]
            or not isinstance(provider, dict) or type(provider.get("id")) is not int
            or provider.get("id") != app["id"] or provider.get("slug") != app["slug"]
            or type(entry.get("id")) is not int or entry["id"] <= 0
            or entry.get("html_url") != prefix + str(entry["id"])
            or _codex_event_time(entry.get("updated_at")) != _codex_event_time(entry.get("created_at"))):
            return None
        receipt_body = _review_body(entry)
        hashes = re.findall(r"\*\*Reviewed commit:\*\* `([0-9a-f]{7,64})`", receipt_body)
        if (len(hashes) != 1 or not head.startswith(hashes[0])
            or git(root, "rev-parse", f"--disambiguate={hashes[0]}", check=False).splitlines() != [head]):
            return None
        if ((name == "code" and not _codex_no_findings_report(receipt_body, head))
            or (name == "security" and (not _codex_informational_report(entry)
                                       or "### 🛡️ Codex Security Review" not in receipt_body))):
            return None
    if (matches["code"][0]["id"] == matches["security"][0]["id"]
        or not _codex_receipts_unedited(root, [matches["code"][0], matches["security"][0]])):
        return None
    return {"code_receipt_url": matches["code"][0]["html_url"],
            "security_receipt_url": matches["security"][0]["html_url"]}


def codex_completion_review(root: Path, pr: dict[str, Any], head: str, inline: list[dict[str, Any]], entries: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str | None]:
    """Join live provider completion and reaction; never accept a bare thumb."""
    candidates = []
    for entry in entries:
        if not _codex_service_user(entry):
            continue
        if _codex_code_completion(_codex_receipt_body(_review_body(entry))):
            candidates.append((entry, None))
        elif receipt_pair := _codex_correlated_receipts(root, pr, head, entry, entries):
            candidates.append((entry, receipt_pair))
    if len(candidates) != 1:
        return None, None
    entry, receipt_pair = candidates[0]
    report_body = _codex_receipt_body(_review_body(entry))
    completion = _codex_code_completion(report_body, corroborated_security=receipt_pair is not None)
    if completion is None:
        return None, "Codex completion layout changed during parsing"
    prefix, completed = completion
    if (not head.startswith(prefix) or pr.get("headRefOid") != head
        or type(entry.get("id")) is not int or entry["id"] <= 0
        or _review_login(entry) == _review_login({"user": pr.get("author")})):
        return None, None
    if git(root, "rev-parse", f"--disambiguate={prefix}", check=False).splitlines() != [head]:
        return None, "Codex completion abbreviated commit is unavailable or ambiguous"
    slug, error = repository_slug(root)
    if error or not slug:
        return None, error or "Codex completion repository identity unavailable"
    security = re.search(r"<!-- codex-security-review:v1 (.*?) -->", " ".join(report_body.split()))
    if security:
        metadata = json.loads(security[1])  # Complete layout was validated above.
        if metadata["repository"] != slug or metadata["pullRequestNumber"] != pr["number"]:
            return None, "Codex completion security activity belongs to another PR"
    host, error = review_repository_host(pr, slug)
    expected_url = f"https://{host}/{slug}/pull/{pr['number']}#issuecomment-{entry.get('id')}"
    if error or host != "github.com" or entry.get("html_url") != expected_url:
        return None, None
    # Versioned no-findings state is explicit completion evidence. Legacy
    # activity-only layouts still require the independent reaction join.
    state_head = _codex_state_summary_body(" ".join(report_body.split()), corroborated_security=receipt_pair is not None)[1]
    reactions, reaction = None, None
    if state_head is None:
        reactions, error = _codex_reactions(root, slug, pr["number"])
        if error:
            return None, None
        reaction = _codex_matching_reaction(entry, completed, reactions)
        if reaction is None:
            return None, None
    elif (created := _codex_event_time(entry.get("created_at"))) is None or (updated := _codex_event_time(entry.get("updated_at"))) is None or created > _codex_event_time(completed) or updated < created or (updated - _codex_event_time(completed)).total_seconds() < -1:
        return None, None
    verified, error = _codex_completion_snapshot(root, pr, inline, entries, reactions, slug)
    if not verified:
        return None, error
    if receipt_pair is not None:
        receipt_urls = {receipt_pair["code_receipt_url"], receipt_pair["security_receipt_url"]}
        receipts = [next((entry for entry in entries if entry.get("html_url") == url), {})
                    for url in (receipt_pair["code_receipt_url"], receipt_pair["security_receipt_url"])]
        if len(receipt_urls) != 2 or not _codex_receipts_unedited(root, receipts):
            return None, "Codex receipt edit history changed or became unavailable during verification"
    timestamp = completed
    security_findings = _codex_security_findings(report_body)
    if receipt_pair is not None:
        security_findings = "no_findings"  # Independently authenticated code and security reports.
    return {"user": entry["user"], "state": "COMMENTED", "commit_id": head,
            "body": f"No findings for {head}.", "created_at": timestamp,
            "source": "codex_completion_reaction", "html_url": entry["html_url"],
            "clearance_scope": "code_and_security" if security_findings == "no_findings" else "code_only",
            "completion_evidence": {"summary_url": entry["html_url"], "reviewed_head": head,
                                    "code_findings": "none", "security_findings": security_findings,
                                    "completed_at": completed, "reaction_id": reaction["id"] if reaction else None,
                                    "reaction_created_at": reaction["created_at"] if reaction else None,
                                    **(receipt_pair or {})}}, None


def _coderabbit_statuses(root: Path, slug: str, head: str) -> list[dict[str, Any]] | None:
    result = run_command(["gh", "api", f"repos/{slug}/commits/{head}/statuses", "--paginate", "--slurp"], root, check=False)
    if result.returncode:
        return None
    try:
        pages = json.loads(result.stdout)
        if not isinstance(pages, list) or not pages or any(not isinstance(page, list) for page in pages):
            return None
        events = [item for page in pages for item in page]
        return events if all(isinstance(item, dict) for item in events) else None
    except ValueError:
        return None


def _coderabbit_native_sources(root: Path, slug: str, head: str, entry: dict[str, Any]) -> tuple[Any, Any]:
    """Read native check inventory and complete authenticated summary history."""
    node_id = entry.get("node_id")
    if not isinstance(node_id, str) or not node_id or len(node_id) > 256:
        return None, None
    checks = run_command(["gh", "api", f"repos/{slug}/commits/{head}/check-runs?filter=all&per_page=100", "--paginate", "--slurp"], root, check=False)
    query = ("query($id:ID!){node(id:$id){... on IssueComment{"
             "id databaseId url body createdAt updatedAt lastEditedAt includesCreatedEdit author{login __typename} "
             "userContentEdits(first:100){totalCount pageInfo{hasNextPage} nodes{"
             "id createdAt updatedAt editedAt editor{login __typename} deletedAt diff}}}}}")
    history = run_command(["gh", "api", "graphql", "-f", "query=" + query, "-f", "id=" + node_id], root, check=False)
    if checks.returncode or history.returncode:
        return None, None
    try:
        pages, payload = json.loads(checks.stdout), json.loads(history.stdout)
        if (not isinstance(pages, list) or not pages or not isinstance(payload, dict) or payload.get("errors")
            or any(not isinstance(page, dict) or not isinstance(page.get("check_runs"), list) for page in pages)):
            return None, None
        inventory = [item for page in pages for item in page["check_runs"]]
        if not all(isinstance(item, dict) for item in inventory):
            return None, None
        return inventory, payload["data"]["node"]
    except (ValueError, TypeError, KeyError):
        return None, None


def _coderabbit_benign_details(context: str) -> bool:
    """Only empty details or count-matched, literal LGTM comments are inert."""
    wrapper = r"\s*<details>\s*<summary><strong>📜 Recent review details</strong></summary>\s*<dl>\s*<dd>\s*(.*?)\s*</dd>\s*</dl>\s*</details>\s*"
    match = re.fullmatch(wrapper, context, re.DOTALL)
    if match is None:
        return False
    if not match[1].strip():
        return True
    additional = re.fullmatch(r"<details>\s*<summary><strong>\s*Additional comments: ([1-9][0-9]*)</strong></summary>\s*<dl>\s*<dd>\s*(.*?)\s*</dd>\s*</dl>\s*</details>", match[1], re.DOTALL)
    if additional is None:
        return False
    item = re.compile(r"\s*<details>\s*<summary><strong>([^<>\r\n]+): 1</strong></summary>\s*<dl>\s*<dd>\s*`([1-9][0-9]*)-([1-9][0-9]*)`: LGTM!\s*(?:Also applies to: [1-9][0-9]*-[1-9][0-9]*\s*)?<!-- cr-comment:v1:[0-9a-f]{24} -->\s*</dd>\s*</dl>\s*</details>\s*")
    contents, count = additional[2], 0
    while contents:
        comment = item.match(contents)
        if comment is None or int(comment[2]) > int(comment[3]):
            return False
        count += 1
        contents = contents[comment.end():]
    return count == int(additional[1])


def _coderabbit_recent_layout(recent: str, slug: str, head: str, branch: str) -> str | None:
    """Adapt observed decoration and head-bound configuration, never erase prose."""
    recent = recent.replace("<br>", "\n")
    icons = {"info": "ℹ️", "cog": "⚙️", "git-commit-horizontal": "📥",
             "file-plus-corner": "📒", "review-details": "📜",
             "message-square-more": ""}
    assets = "https://storage.googleapis.com/coderabbit_public_assets/review-comment-icons-v1/"
    for name, label in icons.items():
        source = f'<source media="(prefers-color-scheme: dark)" srcset="{assets}{name}-dark.svg">'
        for size in (12, 16):
            image = f'<img src="{assets}{name}.svg" width="{size}" height="{size}" align="absmiddle" alt="">'
            for picture in (f"<picture>{image}</picture>", f"<picture>{source}{image}</picture>"):
                recent = recent.replace(picture, label)
    verdict = "No actionable comments were generated in the recent review."
    if recent.startswith(verdict + "\n"):
        recent = verdict + " 🎉" + recent[len(verdict):]
    if recent.count("<!-- review_info_content -->") > 1:
        return None
    recent = recent.replace("<!-- review_info_content -->", "")
    organization = (
        "- **Source mode**: Auto\n- **Repository**: Unavailable\n- **Branch**: Unavailable\n"
        "- **File**: No configuration file from this repository applied\n- **Commit**: Unavailable\n"
        "- **Layers**: Organization UI; Enforced overrides: Organization")
    repository_ui = organization.replace("- **Layers**: Organization UI;", "- **Layers**: Repository UI (base), Organization UI (inherited);")
    for configuration in (organization, repository_ui):
        if recent.count(configuration) == 1 and "- **Configuration used**:" not in recent:
            recent = recent.replace(configuration, "- **Configuration used**: Organization UI")
    if "- **Source mode**:" in recent:
        if not isinstance(branch, str) or not branch or any(c in branch for c in "\r\n<>[]"):
            return None
        configuration = (
            "- **Source mode**: Auto\n"
            f"- **Repository**: [{slug}](<https://github.com/{slug}>)\n"
            f"- **Branch**: [{branch}](<https://github.com/{slug}/tree/{quote(branch, safe='')}>)\n"
            f"- **File**: [.coderabbit.yaml](<https://github.com/{slug}/blob/{head}/.coderabbit.yaml>)\n"
            f"- **Commit**: [{head[:7]}](<https://github.com/{slug}/commit/{head}>)\n"
            "- **Layers**: Repository YAML; Enforced overrides: Organization")
        if recent.count(configuration) != 1 or "- **Configuration used**:" in recent:
            return None
        recent = recent.replace(configuration, f"- **Configuration used**: Repository: {slug}/.coderabbit.yaml")
    return recent


def _coderabbit_status_layout(body: str) -> str:
    """Move one exact native status into the legacy metadata layout, without prose loss."""
    start, end = "<!-- recent_review_status_start -->", "<!-- recent_review_status_end -->"
    recent_start, recent_end = "<!-- recent_review_start -->", "<!-- recent_review_end -->"
    if start not in body and end not in body:
        return body
    if any(body.count(marker) != 1 for marker in (start, end, recent_start, recent_end)):
        return body
    match = re.search(re.escape(start) + r"\s*(.*?)\s*" + re.escape(end), body, re.DOTALL)
    verdict = "No actionable comments were generated in the recent review."
    if match is None or match[1] not in (verdict, verdict + " 🎉"):
        return body
    header = ("<!-- coderabbit-ai-generated:v1 --> "
              "<!-- This is an auto-generated comment: summarize by coderabbit.ai -->")
    if " ".join(body[:match.start()].split()) != header:
        return body  # Nested/quoted status is not an authoritative top-level verdict.
    recent = body.split(recent_start)[1].split(recent_end)[0].strip()
    if recent.startswith("<h6>\n") and recent.endswith("\n</h6>"):
        recent = recent[len("<h6>\n"):-len("\n</h6>")].strip()
    body = body[:match.start()] + body[match.end():]
    return re.sub(re.escape(recent_start) + r".*?" + re.escape(recent_end),
                  lambda _: recent_start + "\n" + match[1] + "\n" + recent + "\n" + recent_end,
                  body, count=1, flags=re.DOTALL)


def coderabbit_completion_review(root: Path, pr: dict[str, Any], head: str, inline: list[dict[str, Any]], entries: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str | None]:
    """Normalise an authenticated automatic review summary, never a chat reply."""
    if not any(_review_login(entry) == "coderabbitai" and "<!-- This is an auto-generated comment: summarize by coderabbit.ai -->" in _review_body(entry) for entry in entries):
        return None, None
    slug, error = repository_slug(root)
    if error or not slug:
        source = re.fullmatch(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/pull/" + re.escape(str(pr["number"])), str(pr.get("url", "")))
        slug = source[1] if source else None
    if not slug or pr.get("headRefOid") != head:
        return None, None
    candidates = []
    for entry in entries:
        user, body = entry.get("user", {}), _review_body(entry)
        if (user.get("login") != "coderabbitai[bot]" or user.get("type") != "Bot"
            or type(user.get("id")) is not int or user["id"] <= 0
            or type(entry.get("id")) is not int or entry["id"] <= 0
            or entry.get("html_url") != f"https://github.com/{slug}/pull/{pr['number']}#issuecomment-{entry['id']}"
            or pr.get("url") != f"https://github.com/{slug}/pull/{pr['number']}"
            or _review_login(entry) == _review_login({"user": pr.get("author")})):
            continue
        structured = _coderabbit_summary_adapter().structured_summary(body, slug, pr["number"], head)
        if structured is not None:
            if not _codex_consistent_author(entry):
                continue
            body = structured["metadata_body"]
        else:
            body = _coderabbit_status_layout(body)
        markers = ("<!-- coderabbit-ai-generated:v1 -->", "<!-- This is an auto-generated comment: summarize by coderabbit.ai -->", "<!-- recent_review_start -->", "<!-- recent_review_end -->")
        if not body.startswith(markers[0]) or any(body.count(marker) != 1 for marker in markers):
            continue
        envelope = body
        envelope = re.sub(r"<!-- autopilot:start -->\s*<!-- autopilot:end -->", "", envelope, flags=re.DOTALL)
        envelope = re.sub(r"<!-- This is an auto-generated comment: all tool run failures by coderabbit.ai -->\s*<!-- end of auto-generated comment: all tool run failures by coderabbit.ai -->", "", envelope, flags=re.DOTALL)
        envelope = re.sub(r"<details>\s*<summary><strong>Merge Risk:</strong>\s*</summary>\s*</details>", "", envelope, flags=re.DOTALL)
        if any(marker in envelope for marker in ("<!-- autopilot:start -->", "<!-- This is an auto-generated comment: all tool run failures by coderabbit.ai -->", "<summary><strong>Merge Risk:</strong>")):
            continue
        coverage = []
        for name in ("review_stack_entry", "recent_review", "walkthrough", "pre_merge_checks_walkthrough", "finishing_touch_checkbox", "tips", "final_review_risk"):
            start, end = f"<!-- {name}_start -->", f"<!-- {name}_end -->"
            if envelope.count(start) != envelope.count(end) or envelope.count(start) > 1:
                break
            if name == "final_review_risk":
                risk = re.findall(re.escape(start) + r"(.*?)" + re.escape(end), envelope, re.DOTALL)
                coverage = re.findall(r"<!-- final_review_risk_coverage:(.*?) -->", risk[0]) if len(risk) == 1 else []
            payload = re.findall(re.escape(start) + r"(.*?)" + re.escape(end), envelope, re.DOTALL)
            if name not in {"recent_review", "final_review_risk"} and any(part.strip() for part in payload):
                break
            if name == "final_review_risk" and payload and re.sub(r"<!-- final_review_risk_coverage:.*? -->", "", payload[0]).strip():
                break
            envelope = re.sub(re.escape(start) + r".*?" + re.escape(end), "", envelope, flags=re.DOTALL)
        if " ".join(envelope.split()) != markers[0] + " " + markers[1]:
            continue  # Unknown top-level prose may contain findings.
        recent = body.split(markers[2])[1].split(markers[3])[0].strip()
        recent = _coderabbit_recent_layout(recent, slug, head, pr.get("headRefName", ""))
        if recent is None:
            continue
        verdict = "No actionable comments were generated in the recent review. 🎉"
        # Only supported metadata text may accompany the outcome. The separately
        # labelled context wrapper admits only empty or literal LGTM details.
        context_start, context_end = "<!-- review_details_start -->", "<!-- review_details_end -->"
        if recent.count(context_start) != recent.count(context_end) or recent.count(context_start) > 1:
            continue
        if context_start in recent:
            context = recent.split(context_start)[1].split(context_end)[0]
            if not _coderabbit_benign_details(context):
                continue
        info = re.sub(re.escape(context_start) + r".*?" + re.escape(context_end), "", recent, flags=re.DOTALL)
        info = re.sub(r"</?(?:details|summary|strong|dl|dd|blockquote)(?: open)?>|<br>", "\n", info)
        fields = [line.strip() for line in info.splitlines() if line.strip()]
        info = "\n".join(fields)
        selected = re.findall(r"^📒 Files selected for processing: ([1-9][0-9]*)$", info, re.MULTILINE)
        paths = re.findall(r"^\* `[^`\r\n]+`$", info, re.MULTILINE)
        if len(selected) > 1 or (paths and not selected) or (selected and int(selected[0]) != len(paths)):
            continue
        metadata_line = (r"(?:ℹ️ Recent review info|⚙️ Run configuration|📥 Commits|📒 Files selected for processing: [1-9][0-9]*"
                         r"|- \*\*Configuration used\*\*: Repository: " + re.escape(slug) + r"/\.coderabbit\.yaml"
                         r"|- \*\*Configuration used\*\*: Organization UI"
                         r"|- \*\*Review profile\*\*: (?:ASSERTIVE|CHILL)|- \*\*Plan\*\*: (?:Team|Essentials)"
                         r"|- \*\*Run ID\*\*: `[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}`"
                         r"|Reviewing files that changed from the base of the PR and between [0-9a-f]{40} and " + re.escape(head) + r"\."
                         r"|\* `[^`\r\n]+`|" + re.escape(verdict)
                         + r"|\*\*Included review availability:\*\* This review used your included allowance\. [0-9]+ included reviews? remain(?:s)? after this review\. Your included PR review attempts over the past 7 days set your current allowance at [0-9]+ reviews? per hour\.)")
        if any(re.fullmatch(metadata_line, field) is None for field in fields):
            continue
        try:
            covered = json.loads(coverage[0], object_pairs_hook=_unique_provider_object) if len(coverage) == 1 else None
        except (ValueError, RecursionError):
            continue
        reviewed_range = re.findall(r"^Reviewing files that changed from the base of the PR and between ([0-9a-f]{40}) and " + re.escape(head) + r"\.$", info, re.MULTILINE)
        created, updated = (_codex_event_time(entry.get(key)) for key in ("created_at", "updated_at"))
        if (not recent.startswith(verdict + "\n") or not recent[len(verdict):].strip().startswith("<details>")
            or covered != {"sourceCommitId": head, "coveredCommitId": head, "kind": "reviewed"}
            or re.findall(r"^- \*\*Configuration used\*\*: (.+)$", info, re.MULTILINE)
            not in ([f"Repository: {slug}/.coderabbit.yaml"], ["Organization UI"])
            or len(re.findall(r"^- \*\*Run ID\*\*: `[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}`$", info, re.MULTILINE)) != 1
            or len(reviewed_range) != 1
            or re.search(r"Actionable comments posted:|Outside diff range comments|cr-indicator-types:potential_issue|review (?:incomplete|skipped|paused)|files skipped", body, re.IGNORECASE)
            or created is None or updated is None or updated < created):
            continue
        merge_base = run_command(["git", "merge-base", str(pr.get("baseRefOid", "")), head], root, check=False)
        if merge_base.returncode or SHA_RE.fullmatch(merge_base.stdout.strip()) is None:
            continue
        if run_command(["git", "merge-base", "--is-ancestor", reviewed_range[0], head], root, check=False).returncode != 0:
            continue
        if structured is not None:
            try:
                reviewed_paths = [path[3:-1] for path in paths]
                if (not selected or len(set(reviewed_paths)) != len(reviewed_paths)
                    or sorted(reviewed_paths) != changed_paths(root, reviewed_range[0], head)):
                    continue
            except (ValueError, CommandFailure):
                continue
        candidates.append({**entry, "state": "COMMENTED", "commit_id": head,
                           "body": f"No findings for {head}.", "source": "coderabbit_completion",
                           "incremental_completion": reviewed_range[0] != merge_base.stdout.strip(), "reviewed_range_start": reviewed_range[0],
                           "structured_summary": structured})
    if len(candidates) != 1:
        return None, None
    candidate = candidates[0]
    structured = candidate.pop("structured_summary")
    if structured is not None:
        native_sources = _coderabbit_native_sources(root, slug, head, candidate)
        binding = _coderabbit_summary_adapter().native_binding(candidate, structured, native_sources[1], native_sources[0], pr, slug, head)
        if binding is None:
            return None, None
        timestamp, completion_evidence = binding["completed_at"], binding
    else:
        statuses = _coderabbit_statuses(root, slug, head)
        if statuses is None:
            return None, "CodeRabbit completion status inventory unavailable"
        updated = _codex_event_time(candidate["updated_at"])
        matches = [event for event in statuses if event.get("context") == "CodeRabbit"
                   and event.get("state") == "success" and type(event.get("id")) is int and event["id"] > 0
                   and isinstance(event.get("creator"), dict)
                   and all(event["creator"].get(key) == candidate["user"].get(key) for key in ("id", "login", "type"))
                   and (created := _codex_event_time(event.get("created_at"))) is not None
                   and abs((created - updated).total_seconds()) <= 5]
        if len(matches) != 1:
            return None, None
        # Append-only commit statuses anchor the existing metadata-only route.
        event = matches[0]
        timestamp = min(updated, _codex_event_time(event["created_at"])).isoformat().replace("+00:00", "Z")
        completion_evidence = {"status_id": event["id"]}
    if candidate["incremental_completion"] and not any(
        _review_login(review) == "coderabbitai" and _review_sha(review) == candidate["reviewed_range_start"]
        and _bot_review_is_acceptable(review, candidate["reviewed_range_start"])
        and (prior_time := _codex_event_time(_review_timestamp(review).replace("+00:00", "Z"))) is not None and prior_time < _codex_event_time(timestamp)
        for review in pr.get("reviews", [])):
        return None, None
    candidate = {**candidate, "created_at": timestamp, "updated_at": timestamp,
                 "completion_evidence": {**completion_evidence, "summary_url": candidate["html_url"], "reviewed_head": head,
                                         "range_start": candidate["reviewed_range_start"], "incremental": candidate["incremental_completion"]}}
    verified, error = _codex_completion_snapshot(root, pr, inline, entries, None, slug)
    if not verified:
        return None, error
    if structured is not None and _coderabbit_native_sources(root, slug, head, candidate) != native_sources:
        return None, "CodeRabbit native check or immutable history inventory changed during verification"
    if structured is None and _coderabbit_statuses(root, slug, head) != statuses:
        return None, "CodeRabbit completion status inventory changed during verification"
    return candidate, None


def _codex_state_summary_informational(entry: dict[str, Any], body: str) -> bool:
    """Validate the observed state header as neutral activity, never clearance."""
    match = re.match(r"(<!-- codex-pull-request-review-summary -->\n)<!-- codex-review-state:v1 ([^\n]+) -->\n", body)
    if match is None:
        return False
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value = dict(pairs)
        if len(value) != len(pairs):
            raise ValueError("duplicate review state key")
        return value
    try:
        state = json.loads(match[2], object_pairs_hook=unique_object)
        if not isinstance(state, dict) or set(state) != {"code_review", "security_review"}:
            return False
        code_only = state["security_review"] == dict.fromkeys(("commit_sha", "has_any_findings", "has_unresolved_findings", "status"))
        summary = match[1] + body[match.end():]
        # The complete parser owns shape, flags, row and metadata consistency.
        # Repeating a separate state parser here can disagree on unknown security.
        completion = _codex_code_completion(body)
        security = re.search(r"<!-- codex-security-review:v1 (.*?) -->", " ".join(summary.split()))
        source = re.fullmatch(r"https://[^/]+/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/([1-9][0-9]*)#issuecomment-[1-9][0-9]*",
                              str(entry.get("html_url") or entry.get("url") or ""))
        if completion is None or source is None:
            return False
        if code_only:
            return security is None and state["code_review"]["commit_sha"].startswith(completion[0])
        if security is None:
            return False
        metadata = json.loads(security[1], object_pairs_hook=unique_object)
        return bool(state["code_review"]["commit_sha"].startswith(completion[0])
                    and state["security_review"]["commit_sha"] == metadata["headSha"]
                    and metadata["repository"] == source[1] + "/" + source[2]
                    and metadata["pullRequestNumber"] == int(source[3]))
    except (ValueError, TypeError, KeyError, RecursionError):
        return False


def _codex_informational_report(entry: dict[str, Any]) -> bool:
    """Recognise fixed non-finding reports, including stale ones, as neutral."""
    if _review_login(entry) != "chatgpt-codex-connector":
        return False
    report_body = _codex_receipt_body(_review_body(entry))
    if "<!-- codex-review-state:" in report_body:
        return _codex_state_summary_informational(entry, report_body)
    if _codex_code_completion(report_body):
        return True
    body = " ".join(report_body.split())
    security = re.fullmatch(
        r"### 🛡️ Codex Security Review · _Automatically triggered_ "
        r"Security review completed\. No security issues were found in this pull request\. "
        r"\*\*Reviewed commit:\*\* `([0-9a-f]{7,64})` "
        r"\[View security finding report\]\(https://chatgpt\.com/codex/cloud/tasks/task_[A-Za-z0-9_]+\) "
        r"_Only the user who started this review can view the report in Codex\._ "
        r"<details> <summary>ℹ️ About Codex security reviews in GitHub</summary> <br/> "
        r"This is an experimental Codex feature\. Security reviews are triggered when: "
        r'- You comment "@codex security review" '
        r'- A regular code review gets triggered \(for example, "@codex review" or when a PR is opened\), '
        r"and you’re opted in so security review runs alongside code review "
        r"Once complete, Codex will leave suggestions, or a comment if no findings are found\. </details>",
        body,
    )
    if security:
        return True
    summary = re.fullmatch(
        r"<!-- codex-pull-request-review-summary --> <!-- codex-security-review:v1 (\{.+?\}) --> "
        r"## Codex Review Summary This comment shows the latest Codex review activity on this pull request\. "
        r"\| Review \| Status \| Commit \| Review trigger \| \| --- \| --- \| --- \| --- \| "
        r"\| 📝 \*\*Code Review\*\* \| ✅ \*\*Completed\*\* <relative-time datetime=\"([^\"]+)\">\2</relative-time> \| `([0-9a-f]{7,64})` \| (?:Manual request|Automatic|PR opened|New commits|Draft marked ready) \| "
        r"\| 🔒 \*\*Security Review\*\* \| ✅ \*\*Completed\*\* <relative-time datetime=\"([^\"]+)\">\4</relative-time> \| `([0-9a-f]{7,64})` \| (?:Manual request|Automatic|PR opened|New commits|Draft marked ready) \| "
        r"<details> <summary>ℹ️ About Codex in GitHub</summary> <br/> "
        r"\[Your team has set up Codex to review pull requests in this repo\]\(https://chatgpt\.com/codex/cloud/settings/general\)\. Reviews are triggered when you "
        r'- Open a pull request for review - Mark a draft as ready - Comment "@codex review" or "@codex security review"\. '
        r"Codex reacts with 👀 while any review is running, comments if it has suggestions, and reacts with 👍 once all reviews finish with no findings\. </details>",
        body,
    )
    if not summary:
        return False
    try:
        metadata = json.loads(summary[1], object_pairs_hook=_unique_provider_object)
    except (ValueError, RecursionError):
        return False
    return (isinstance(metadata, dict)
            and set(metadata) == {"blockingSeverityThreshold", "headSha", "mergeGateEnabled", "pullRequestNumber", "repository", "status"}
            and metadata["status"] == "completed"
            and isinstance(metadata["headSha"], str)
            and bool(re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", metadata["headSha"]))
            and all(metadata["headSha"].startswith(summary[index]) for index in (3, 5))
            and isinstance(metadata["blockingSeverityThreshold"], str)
            and metadata["blockingSeverityThreshold"] in {"P0", "P1", "P2", "P3"}
            and type(metadata["mergeGateEnabled"]) is bool
            and type(metadata["pullRequestNumber"]) is int and metadata["pullRequestNumber"] > 0
            and isinstance(metadata["repository"], str)
            and bool(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", metadata["repository"])))


TESSL_ZERO_FINDING_REVIEW_TEMPLATE = """## Tessl Reviewer

### Changes approved

The documentation adds a disposable synthetic missing-description example, an explicit author edit, and a validation rerun, while distinguishing structural validation from repair and execution authority. No actionable concerns were supplied for reconciliation. The diff was inspected read-only; the documented commands and runtime results were not independently executed.

<details>
<summary>Working with this review</summary>

**Verify before acting.** These findings are AI-generated and not authoritative. Check each one against the code, yourself or with an agent, before acting on it.

**Answer each finding on its thread:**

- **Addressed**: you changed the code. Say what changed.
- **Refuted**: the finding is wrong about the code.
- **Declined**: the finding is right, and you are not changing it. Say why.

**Reviews are incremental.** The first review shows every valid optional and required finding. A later round checks the latest changes and earlier findings, and adds a fresh finding only when it requires changes. It never repeats one you refuted or declined. The configured request-changes severity sets the consequence baseline, and review mode sets the strength required to block. Ask for a full review to inspect the whole change and show optional findings again.

**Lenses are configurable.** Add your own and scope them to paths with globs. Keep the set small so findings stay distinct. See https://docs.tessl.io/tutorials/setting-up-agentic-code-review#route-reviews-with-yaml
</details>

Mention `@tessl-reviewer` to run another review.

<!-- tessl-code-review:run:v1 -->
<!-- tessl-code-review:workflow-run:v1 id={run} -->
<!-- tessl-code-review:result:v1 approved=true findings-total=0 findings-unplaced=0 -->

<!-- tessl-code-review:ai-notice:v1 This review was generated by an AI system. Validate and verify its claims before taking action. -->"""


def _tessl_review_is_clean(review: dict[str, Any]) -> bool:
    """Recognise only the complete observed envelope, never arbitrary praise.

    Unknown narratives require inspection even when their counters say zero.
    This recogniser alone grants neither freshness nor check-run authority.
    """
    user = review.get("user")
    if (not isinstance(user, dict) or user.get("login") != "tessl-reviewer[bot]"
        or user.get("type") != "Bot" or user.get("id") != 325629464
        or type(review.get("id")) is not int or review["id"] <= 0
        or review.get("state") != "APPROVED"):
        return False
    body = _review_body(review)
    run = re.findall(r"<!-- tessl-code-review:workflow-run:v1 id=([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}) -->", body)
    return len(run) == 1 and body == TESSL_ZERO_FINDING_REVIEW_TEMPLATE.format(run=run[0])


def _tessl_review_is_acceptable(review: dict[str, Any], head_sha: str) -> bool:
    return (_tessl_review_is_clean(review) and _review_sha(review) == head_sha
            and review.get("tessl_check_verified") is True)


def _tessl_historical_clean_review(review: dict[str, Any]) -> bool:
    """Known clean historical text is neutral, even after approval dismissal.

    This never supplies current clearance or erases a finding. Keep the complete
    envelope allowlist: dismissal and zero counters alone prove neither claim.
    """
    if review.get("state") not in {"APPROVED", "DISMISSED"}:
        return False
    body = _review_body(review)
    observed = (
        "The change adds a documentation-only name-mismatch recovery example covering rejection, "
        "an explicit directory rename, and a passing rerun, while preserving the structural-validation "
        "and candidate-identity caveats. No actionable concerns were supplied for reconciliation, "
        "and no findings are surfaced."
    )
    known = TESSL_ZERO_FINDING_REVIEW_TEMPLATE.split("### Changes approved\n\n", 1)[1].split("\n\n<details>", 1)[0]
    return _tessl_review_is_clean({**review, "state": "APPROVED",
                                   "body": body.replace(observed, known, 1)})


def tessl_check_inventory(root: Path, slug: str, head: Any, hostname: str | None = None) -> tuple[list[dict[str, Any]], str | None]:
    """Read complete native check metadata; rollup labels cannot authenticate an App."""
    if not isinstance(head, str) or not SHA_RE.fullmatch(head):
        return [], "Tessl check inventory requires a complete head SHA"
    host_args = ["--hostname", hostname] if hostname is not None else []
    result = run_command(["gh", "api", f"repos/{slug}/commits/{head}/check-runs?filter=all&per_page=100",
                          *host_args, "--paginate", "--slurp"], root, check=False)
    if result.returncode:
        return [], "Tessl check inventory unavailable"
    try:
        pages = json.loads(result.stdout)
        if not isinstance(pages, list) or not pages:
            raise ValueError("missing pages")
        checks = []
        for page in pages:
            if (not isinstance(page, dict) or not isinstance(page.get("check_runs"), list)
                or any(not isinstance(check, dict) for check in page["check_runs"])):
                raise ValueError("invalid check page")
            checks.extend(page["check_runs"])
        return checks, None
    except (ValueError, TypeError):
        return [], "Tessl check inventory malformed"


def _join_tessl_review_check(review: dict[str, Any], pr: dict[str, Any]) -> dict[str, Any]:
    """Join the native review to its exact completed successful App run."""
    runs = re.findall(r"<!-- tessl-code-review:workflow-run:v1 id=([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}) -->", _review_body(review))
    checks = pr.get("tessl_check_runs")
    if len(runs) != 1 or not isinstance(checks, list):
        return {**review, "tessl_check_verified": False}
    matching = [check for check in checks if isinstance(check, dict)
                and check.get("name") == "Tessl Reviewer"
                and type(check.get("id")) is int and check["id"] > 0
                and check.get("head_sha") == pr.get("headRefOid") == _review_sha(review)
                and check.get("status") == "completed"
                and check.get("conclusion") == "success"
                and isinstance(check.get("app"), dict)
                and type(check["app"].get("id")) is int and check["app"]["id"] == 4850038
                and check["app"].get("slug") == "tessl-reviewer"
                and check.get("details_url") == "https://tessl.io/go/code-review-runs/" + runs[0]]
    return {**review, "tessl_check_verified": len(matching) == 1, "incremental_completion": True}


def _bot_review_is_acceptable(review: dict[str, Any], head_sha: str) -> bool:
    if review.get("record_only_reply"):
        return False
    state = str(review.get("state") or "").upper()
    if state not in {"APPROVED", "COMMENTED"}:
        return False
    body = _review_body(review)
    receipt_markers = re.findall(r"<!-- codex-review-receipt:[^>]* -->", body)
    if receipt_markers and (receipt_markers != ["<!-- codex-review-receipt:v1 -->"]
                            or not body.startswith("<!-- codex-review-receipt:v1 -->\n\n")):
        return False
    login = _review_login(review)
    if login not in BOT_REVIEWERS:
        return False
    if login == "tessl-reviewer":
        return _tessl_review_is_acceptable(review, head_sha)
    if _bot_review_has_explicit_no_findings(body, head_sha):
        # A bare chat reply may answer a missing or edited record-only request.
        # Require hosted review metadata before treating it as clearance.
        return login != "coderabbitai" or _review_sha(review) == head_sha
    if login == "chatgpt-codex-connector" and _codex_positive_clearance(body, head_sha):
        return True
    return (login == "coderabbitai"
            and _bot_review_has_explicit_no_findings(_coderabbit_reply_statement(body), head_sha))


def _bot_review_has_blocked_response(body: str, *, parsed_reply: bool = False, login: str = "") -> bool:
    if parsed_reply:
        return bool(BOT_REPLY_BLOCKED_RE.search(body))
    if login == "coderabbitai" and _coderabbit_reply_body(body):
        body = _coderabbit_reply_statement(body)
        if not body:
            return True
    if (
        BOT_REVIEW_BLOCKED_RE.search(body)
        or UNAUTHORIZED_RESPONSE_RE.search(body)
        or STANDALONE_AUTH_RESPONSE_RE.search(body)
        or AUTH_STATUS_RESPONSE_RE.search(body)
        or PERMISSION_DENIED_RESPONSE_RE.search(body)
        or AUTH_ERROR_RESPONSE_RE.search(body)
        or CREDENTIAL_FAILURE_RESPONSE_RE.search(body)
    ):
        return True
    return bool(AUTH_FAILURE_SEQUENCE_RE.search(body))


def _coderabbit_unbound_positive(body: str, head_sha: str) -> bool:
    """Treat a valid outer no-findings reply as neutral when only decoration names the head."""
    statement = _coderabbit_reply_statement(body)
    return bool(re.fullmatch(r"No (?:actionable )?(?:comments?|findings?)[.!]?", statement, re.IGNORECASE)
                and not _body_has_current_head(statement, head_sha)
                and not _bot_review_has_blocked_response(body, login="coderabbitai"))


def _should_replace_timestamped_candidate(
    previous: dict[str, Any] | None,
    timestamp: str,
    previous_timestamp: str,
) -> bool:
    """Select the later candidate while preserving blockers on timestamp ties.

    GitHub timestamps are second-granular. When two responses share a timestamp,
    the API order remains meaningful for positive evidence, but a blocker must
    never be overwritten by a later-arriving positive response.
    """
    if previous is None or timestamp > previous_timestamp:
        return True
    if timestamp < previous_timestamp:
        return False
    previous_is_blocked = _bot_review_has_blocked_response(_review_body(previous), login=_review_login(previous))
    return not previous_is_blocked


def current_head_bot_reviews(reviews: list[Any], head_sha: str) -> dict[str, dict[str, Any]]:
    """Return the latest relevant review response for each required bot."""
    latest: dict[str, dict[str, Any]] = {}
    for review in reviews:
        if not isinstance(review, dict):
            continue
        login = _review_login(review)
        if login not in BOT_REVIEWERS:
            continue
        body = _review_body(review)
        review_sha = _review_sha(review)
        is_current_head = review_sha == head_sha
        is_blocked = _bot_review_has_blocked_response(body, login=login)
        is_bound_to_other_head = _body_has_other_head(body, head_sha)
        is_unbound_blocker = is_blocked and not review_sha and not is_bound_to_other_head
        if not (is_current_head or is_unbound_blocker):
            continue
        previous = latest.get(login)
        review_timestamp = _review_timestamp(review)
        previous_timestamp = _review_timestamp(previous) if previous else ""
        if _should_replace_timestamped_candidate(previous, review_timestamp, previous_timestamp):
            latest[login] = review
    return latest


def review_comments(root: Path, number: int) -> tuple[list[dict[str, Any]], str | None]:
    return _paginated_comments(root, f"pulls/{number}/comments", "review-comment")


def _paginated_comments(root: Path, path: str, label: str) -> tuple[list[dict[str, Any]], str | None]:
    slug, error = repository_slug(root)
    if error or not slug:
        return [], error or f"repository slug unavailable for {label} query"
    return review_inventory_collection(root, f"repos/{slug}/{path}")


def review_repository_host(pr: dict[str, Any], slug: str) -> tuple[str | None, str | None]:
    """Bind API routing to the validated HTTPS pull-request identity."""
    value = pr.get("url")
    if not isinstance(value, str):
        return None, "PR URL is missing or malformed"
    try:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", parsed.netloc) or parsed.path != f"/{slug}/pull/{pr['number']}" or parsed.query or parsed.fragment:
            return None, "PR URL must identify the matching HTTPS repository and pull request"
        return parsed.netloc, None
    except ValueError:
        return None, "PR URL has an invalid host or port"


def review_inventory_collection(root: Path, path: str, hostname: str | None = None) -> tuple[list[dict[str, Any]], str | None]:
    """Decode all REST pages; unavailable or malformed sources never mean empty."""
    host_args = ["--hostname", hostname] if hostname is not None else []
    result = run_command(["gh", "api", path, *host_args, "--paginate", "--slurp"], root, check=False)
    if result.returncode:
        detail = (result.stderr.strip() or result.stdout.strip() or "command failed").splitlines()[0]
        return [], f"review inventory unavailable: {path}: {detail}"
    try:
        pages = json.loads(result.stdout)
        if not isinstance(pages, list) or not pages or any(
            not isinstance(page, list) or any(not isinstance(entry, dict) for entry in page)
            for page in pages
        ):
            raise ValueError("expected paginated arrays of objects")
        entries = [entry for page in pages for entry in page]
        for entry in entries:
            user = entry.get("user")
            if not isinstance(user, dict) or not isinstance(user.get("login"), str) or not user["login"] or "body" not in entry or (entry["body"] is not None and not isinstance(entry["body"], str)):
                raise ValueError("source author or body unavailable")
            commit_id = entry.get("commit_id")
            if commit_id is not None and (not isinstance(commit_id, str) or not SHA_RE.fullmatch(commit_id)):
                raise ValueError("source commit_id must be a full SHA or null")
            if path.endswith("/reviews") and (
                not isinstance(entry.get("state"), str)
                or entry["state"] not in {"APPROVED", "COMMENTED", "CHANGES_REQUESTED", "DISMISSED", "PENDING"}
            ):
                raise ValueError("formal review state is missing or invalid")
        return entries, None
    except (ValueError, TypeError) as exc:
        return [], f"invalid review inventory: {path}: {exc}"


def clearance_sources(
    reviews: list[dict[str, Any]],
    inline: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    *,
    resolve_review_tree: Callable[[str], str] | None = None,
    qualify_review: Callable[[dict[str, Any]], bool] | None = None,
) -> list[dict[str, str]]:
    """Fingerprint all authors' review sources, not just bots or open threads."""
    from pr_review_clearance import _absolute_http_url

    sources: dict[str, dict[str, str]] = {}
    for kind, entries in (("review", reviews), ("inline", inline), ("comment", comments)):
        for entry in entries:
            user = entry.get("user")
            login = user.get("login") if isinstance(user, dict) else None
            url = entry.get("html_url")
            body = entry.get("body")
            if not isinstance(login, str) or not login or not isinstance(url, str) or not url or "body" not in entry or (body is not None and not isinstance(body, str)):
                raise ValueError("review source is missing its author, URL or body")
            if not _absolute_http_url(url):
                raise ValueError("review source URL must be an absolute HTTP or HTTPS URI")
            login = login.removesuffix("[bot]")
            if not login:
                raise ValueError("review source author is empty after normalization")
            digest = hashlib.sha256(json.dumps(
                {"kind": kind, "author": login, "body": body,
                 "commit": entry.get("commit_id"), "state": entry.get("state"),
                 "updated_at": entry.get("updated_at"), "submitted_at": entry.get("submitted_at")},
                sort_keys=True, separators=(",", ":"),
            ).encode()).hexdigest()
            if url in sources:
                raise ValueError("duplicate review source URL")
            source = {"url": url, "sha256": digest, "kind": kind, "author": login}
            if (
                kind == "review"
                and resolve_review_tree is not None
                and (qualify_review is None or qualify_review(entry))
            ):
                validated_sha = _review_sha(entry)
                if validated_sha is not None:
                    if not SHA_RE.fullmatch(validated_sha):
                        raise ValueError("formal review commit must be a full SHA")
                    tree_sha = resolve_review_tree(validated_sha)
                    if not SHA_RE.fullmatch(tree_sha):
                        raise ValueError("formal review commit tree must be a full SHA")
                    source.update(validated_sha=validated_sha, tree_sha=tree_sha)
            sources[url] = source
    return sorted(sources.values(), key=lambda source: source["url"])


def collect_clearance_sources(root: Path, number: int, slug: str, hostname: str) -> tuple[list[dict[str, str]], str | None]:
    """Collect the full review, inline-comment and issue-comment inventories."""
    collections: list[list[dict[str, Any]]] = []
    for path in (f"pulls/{number}/reviews", f"pulls/{number}/comments", f"issues/{number}/comments"):
        entries, error = review_inventory_collection(root, f"repos/{slug}/{path}", hostname)
        if error:
            return [], error
        collections.append(entries)
    try:
        return clearance_sources(*collections), None
    except ValueError as exc:
        return [], str(exc)


def inspection_request_body(reviewer: str, head: str, clarify: bool, source: str | None = None,
                 retry_source: str | None = None) -> str:
    """Build a bounded inspection or recorded-review clarification request."""
    if reviewer not in {"codex", "coderabbitai"} or not SHA_RE.fullmatch(head):
        raise ValueError("unsupported reviewer or non-full head")
    if clarify and (reviewer != "coderabbitai" or not source):
        raise ValueError("clarification requires CodeRabbit's current-head source URL")
    if retry_source and (reviewer != "coderabbitai" or clarify or source):
        raise ValueError("retry requires CodeRabbit's unavailable-review source URL")
    if clarify:
        return (f"@coderabbitai Report the outcome of the automated CodeRabbit code review recorded at {source} for {head}. "
                "Determine whether that recorded code review completed; if it did not, identify the gap. "
                "Refresh that exact linked GitHub comment once through authenticated read-only access; "
                "use its current body and update time rather than a cached earlier version. "
                "If the source cannot be refreshed or is no longer bound to this head, report that evidence gap. "
                "Report recorded findings and evidence limits. Do not repeat inspection. "
                "Only if the recorded review completed and has no actionable comments, "
                f"reply with exactly `Recorded review status for {head}: completed; no actionable comments recorded.` "
                "Otherwise report the recorded findings or evidence limits instead of that sentence. "
                "This response is informational only. Do not issue a clearance verdict or an approval. "
                "Do not hide findings or a failed or incomplete review. "
                "This requests recorded status only, not approval, merge or thread resolution. "
                "Do not enable paid services or change source.")
    if retry_source:
        action = f"Retry the full review for {head} after the unavailable response at {retry_source}. Independently inspect the current PR diff"
        mention = "@coderabbitai full review"
    else:
        action = f"Independently inspect the current PR diff for {head}"
        mention = "@codex review" if reviewer == "codex" else "@coderabbitai full review"
    separator = "\n\n" if reviewer == "coderabbitai" and not clarify else " "
    formal = ("Publish the normal automatic review completion or a formal review on this exact head; "
              "a conversational reply alone cannot provide CodeRabbit clearance. " if reviewer == "coderabbitai" else "")
    return (f"{mention}{separator}{action}. Only if inspection completed and there are no remaining findings, "
            f"state `No findings for {head}.`; otherwise list actionable findings. "
            "For a completed no-findings inspection, use that standalone statement as the only prose "
            "outside the standard provider wrapper. Only provider tool traces or fixed benign status explanations "
            "may appear in analysis; report substantive limitations or findings instead of a no-findings verdict. "
            "Do not hide findings or a failed or incomplete inspection to fit this format. "
            "This requests inspection evidence only, not approval, merge or thread resolution. "
            + formal + "Do not enable paid services or change source.")


def issue_comments(root: Path, number: int) -> tuple[list[dict[str, Any]], str | None]:
    return _paginated_comments(root, f"issues/{number}/comments", "issue-comment")


def authenticated_review_actor(root: Path) -> dict:
    """Look up and validate the actor used to authenticate request comments."""
    actor = json.loads(run_command(["gh", "api", "user"], root).stdout)
    if (not isinstance(actor, dict) or type(actor.get("id")) is not int or actor["id"] <= 0
        or not isinstance(actor.get("login"), str) or not actor["login"]):
        raise ValueError("authenticated request actor is unavailable")
    return actor


def reinspection_request_body(head: str, source: str) -> str:
    """Share the exact source-bound full-inspection request identity."""
    return (inspection_request_body("coderabbitai", head, False)
            + f" Reinspection follows the later outstanding concern at {source}. "
            "Address that concern and the current PR metadata explicitly.")


def recorded_review_entries(pr: dict[str, Any], entries: list[dict[str, Any]], head: str) -> list[dict[str, Any]]:
    """Bind chat replies to unedited authenticated requests; never grant status clearance."""
    prefix = str(pr.get("url") or "") + "#issuecomment-"
    requests: list[tuple[Any, int]] = []
    for entry in entries:
        user = entry.get("user") or {}
        created = _codex_event_time(entry.get("created_at"))
        url = str(entry.get("html_url") or "")
        if (not isinstance(user.get("login"), str) or not user["login"] or user.get("type") != "User"
            or type(user.get("id")) is not int or user["id"] <= 0 or not created
            or not url.startswith(prefix) or not re.fullmatch(r"[1-9][0-9]*", url[len(prefix):])):
            continue
        body = _review_body(entry)
        # This is denial-only provenance: losing a source or changing evaluators
        # must never promote an informational reply into independent clearance.
        for source_url in set(re.findall(re.escape(prefix) + r"[1-9][0-9]*", body)):
            ordinary = inspection_request_body("coderabbitai", head, False)
            historical = ordinary.replace(
                f"@coderabbitai full review\n\nIndependently inspect the current PR diff for {head}",
                f"@coderabbitai Clarify your inspection evidence at {source_url} for {head}. "
                "Confirm whether independent inspection completed; if it did not, identify the gap. Do not repeat inspection")
            current = inspection_request_body("coderabbitai", head, True, source_url)
            heading = current.replace(
                "Only if the recorded review completed and has no actionable comments, "
                f"reply with exactly `Recorded review status for {head}: completed; no actionable comments recorded.` "
                "Otherwise report the recorded findings or evidence limits instead of that sentence. ",
                f"Use the heading `Recorded review status for {head}`. ")
            if body in {current, heading, historical}:
                requests.append((created, int(url[len(prefix):])))
    result = []
    for entry in entries:
        body = _review_body(entry)
        created = _codex_event_time(entry.get("created_at"))
        effective = _codex_event_time(entry.get("updated_at", entry.get("created_at")))
        reply_url = str(entry.get("html_url") or "")
        reply_id = (int(reply_url[len(prefix):]) if reply_url.startswith(prefix)
                    and re.fullmatch(r"[1-9][0-9]*", reply_url[len(prefix):]) else 0)
        bound = bool(created and effective and effective >= created and reply_id)
        # Creation IDs cannot order edits within the provider's timestamp second.
        previous = [time for time, _ in requests if bound and time <= effective]
        # Automatic review summaries remain independent; only chat-shaped replies
        # can answer a record-reading request. Ambiguous same-time modes fail closed.
        chat = bool(_coderabbit_reply_body(body) or body.startswith("Recorded review status for ")
                    or _bot_review_has_explicit_no_findings(body, head))
        if _review_login(entry) == "coderabbitai" and chat and not bound and requests:
            entry = {**entry, "record_only_reply": True, "record_status_unbound": True}
        if _review_login(entry) == "coderabbitai" and chat and previous:
            # Chronology cannot prove which overlapping request a delayed chat answers.
            entry = {**entry, "record_only_reply": True}
        result.append(entry)
    return result


def _coderabbit_action_notification(entry: dict[str, Any]) -> bool:
    """A fixed command acknowledgement supplies neither findings nor clearance."""
    user = entry.get("user")
    if (not isinstance(user, dict) or type(user.get("id")) is not int
        or user["id"] != 136622811 or user.get("login") != "coderabbitai[bot]"
        or user.get("type") != "Bot" or not _codex_consistent_author(entry)):
        return False
    return re.fullmatch(
        r"<!-- coderabbit-ai-generated:v1 -->\n\n"
        r"<!-- This is an auto-generated reply by CodeRabbit -->\n"
        r"<!-- CodeRabbit review command invocation: v2:[0-9a-f]{64} -->\n"
        r"<details>\n<summary>Action performed</summary>\n<dl>\n<dd>\n<br>\n\n"
        r"Full review finished\.\n\n</dd>\n</dl>\n</details>\n?", _review_body(entry)) is not None


def _neutral_recorded_reply(entry: dict[str, Any], head: str) -> bool:
    """Recognise only complete benign record-status replies, never findings."""
    if not entry.get("record_only_reply") or entry.get("record_status_unbound"):
        return False
    status = f"Recorded review status for {head}: completed; no actionable comments recorded."
    body = _review_body(entry)
    if body == status or _bot_review_has_explicit_no_findings(body, head):
        return True
    for statement in (status, f"No findings for {head}."):
        if body == ("<!-- This is an auto-generated reply by CodeRabbit -->\n\n"
                    + statement + "\n\n_You are interacting with an AI system._"):
            return True
    # The existing strict provider parser rejects appended prose/hidden findings.
    candidate = {**entry, "state": "COMMENTED", "record_only_reply": False,
                 "body": body.replace(status, f"No findings for {head}.", 1)}
    return _bot_review_is_acceptable(candidate, head)


def current_head_bot_comments(comments: list[dict[str, Any]], head_sha: str) -> dict[str, dict[str, Any]]:
    """Return the latest current-head inline review comment for each bot."""
    latest: dict[str, dict[str, Any]] = {}
    for comment in comments:
        user = comment.get("user")
        author = comment.get("author")
        login = user.get("login") if isinstance(user, dict) else author.get("login") if isinstance(author, dict) else ""
        login = str(login or "").removesuffix("[bot]")
        if login not in BOT_REVIEWERS or str(comment.get("commit_id") or comment.get("commitOid") or "") != head_sha:
            continue
        previous = latest.get(login)
        timestamp = str(comment.get("created_at") or comment.get("createdAt") or "")
        previous_timestamp = str(previous.get("created_at") or previous.get("createdAt") or "") if previous else ""
        if _should_replace_timestamped_candidate(previous, timestamp, previous_timestamp):
            latest[login] = comment
    return latest


def current_head_bot_issue_comments(comments: list[dict[str, Any]], head_sha: str) -> dict[str, dict[str, Any]]:
    """Return each bot's latest relevant issue comment.

    Positive no-findings comments must name the current head later in the
    review lane. Blocked/error responses are relevant even when they do not
    repeat the head, so a newer unbound failure cannot leave stale positive
    evidence selected.
    """
    latest: dict[str, dict[str, Any]] = {}
    for comment in comments:
        user = comment.get("user")
        author = comment.get("author")
        login = user.get("login") if isinstance(user, dict) else author.get("login") if isinstance(author, dict) else ""
        login = str(login or "").removesuffix("[bot]")
        body = str(comment.get("body") or "")
        if login not in BOT_REVIEWERS:
            continue
        if (_codex_informational_report(comment) or _neutral_recorded_reply(comment, head_sha)
            or _coderabbit_action_notification(comment)):
            continue
        if login == "coderabbitai" and _coderabbit_unbound_positive(body, head_sha):
            continue
        is_current_head = (_body_has_current_head(body, head_sha)
                           or (login == "chatgpt-codex-connector"
                               and _codex_positive_clearance(body, head_sha)))
        is_blocked = _bot_review_has_blocked_response(body, login=login)
        is_bound_to_other_head = _body_has_other_head(body, head_sha)
        is_positive = bool(BOT_REVIEW_NO_FINDINGS_RE.search(body))
        is_relevant = (is_positive and is_current_head) or (is_blocked and not is_bound_to_other_head)
        if not (is_current_head or is_relevant):
            continue
        previous = latest.get(login)
        timestamp = _comment_timestamp(comment)
        previous_timestamp = _comment_timestamp(previous) if previous else ""
        if _should_replace_timestamped_candidate(previous, timestamp, previous_timestamp):
            latest[login] = comment
    return latest

def _comment_timestamp(comment: dict[str, Any]) -> str:
    created = _ordered_event_time(comment.get("created_at") or comment.get("createdAt"))
    updated = _ordered_event_time(comment.get("updated_at") or comment.get("updatedAt"))
    return max(created, updated)


def _review_timestamp(review: dict[str, Any]) -> str:
    """Return the latest submitted or updated timestamp, or an empty string."""
    submitted = _ordered_event_time(review.get("submittedAt") or review.get("submitted_at"))
    updated = _ordered_event_time(review.get("updatedAt") or review.get("updated_at"))
    return max(submitted, updated)


def _ordered_event_time(value: Any) -> str:
    """Order UTC event times consistently with and without subsecond precision."""
    parsed = _codex_event_time(value)
    return parsed.isoformat(timespec="microseconds") if parsed else str(value or "")


def _review_blocker_shape_hints(login: str, kind: str, body: str, head: str) -> set[str]:
    """Describe known evidence gaps; hints never grant or remove clearance."""
    if kind != "comment":
        return set()
    if login == "coderabbitai" and "<!-- This is an auto-generated comment: summarize by coderabbit.ai -->" in body:
        for name in ("walkthrough", "pre_merge_checks_walkthrough"):
            start, end = f"<!-- {name}_start -->", f"<!-- {name}_end -->"
            section = re.search(re.escape(start) + r"(.*?)" + re.escape(end), body, re.DOTALL)
            if body.count(start) == body.count(end) == 1 and section and section[1].strip():
                return {"coderabbit_nonempty_review_sections"}
    if login == "chatgpt-codex-connector" and "<!-- codex-pull-request-review-summary -->" in body:
        markers = re.findall(r"<!-- codex-review-state:v1 ([^\n]*?) -->", body)
        if len(markers) != 1:
            return set()
        try:
            state = json.loads(markers[0], object_pairs_hook=_unique_provider_object)
        except (ValueError, TypeError, RecursionError):
            return set()
        if not isinstance(state, dict) or set(state) != {"code_review", "security_review"}:
            return set()
        code, security = state["code_review"], state["security_review"]
        if (isinstance(code, dict)
            and set(code) == {"commit_sha", "has_any_findings", "has_unresolved_findings", "status"}
            and code["commit_sha"] == head and code["status"] == "completed"
            and code["has_any_findings"] is False and code["has_unresolved_findings"] is False
            and isinstance(security, dict)
            and set(security) == {"commit_sha", "has_any_findings", "has_unresolved_findings", "status"}
            and security["commit_sha"] == head and security["status"] == "completed"
            and security["has_any_findings"] is None and security["has_unresolved_findings"] is None):
            return {"codex_security_findings_unknown"}
    return set()


def outstanding_bot_concerns(
    reviews: list[dict[str, Any]], inline: list[dict[str, Any]],
    comments: list[dict[str, Any]], head_sha: str, *,
    diagnostics: dict[str, list[str]] | None = None,
) -> list[str]:
    """Head advancement and unavailable responses cannot erase review concerns."""
    concerns: dict[str, list[tuple[str, str, int]]] = {}
    clearances: dict[str, list[tuple[str, str, int]]] = {}
    for kind, entries in (("review", reviews), ("inline", inline), ("comment", comments)):
        for index, entry in enumerate(entries):
            login = _review_login(entry)
            if login not in BOT_REVIEWERS:
                continue
            if kind == "comment" and (_codex_informational_report(entry)
                                      or _neutral_recorded_reply(entry, head_sha)
                                      or _coderabbit_action_notification(entry)):
                continue
            body = _review_body(entry)
            sha = _review_sha(entry)
            # Missing metadata cannot hide body-bound concerns or grant clearance.
            body_bound_source = kind in {"review", "inline"} and not sha and (
                _body_has_current_head(body, head_sha)
                or (kind == "review" and entry.get("state") == "CHANGES_REQUESTED")
            )
            if kind != "comment" and not sha and not body_bound_source:
                continue
            if kind == "comment" and not _body_has_current_head(body, head_sha) and re.fullmatch(r"\s*no\s+(?:actionable\s+)?(?:comments?|findings?)[.!]?\s*", body, re.IGNORECASE):
                continue  # Unbound bare positives neither clear nor add a concern.
            if (kind == "comment" and login == "coderabbitai"
                and _coderabbit_unbound_positive(body, head_sha)):
                continue  # A parsed unbound positive is neutral, never clearance.
            candidate = entry if kind == "review" else {**entry, "state": "COMMENTED"}
            if (kind == "comment" and login == "chatgpt-codex-connector"
                and _codex_positive_clearance(body, None)
                and not _codex_positive_clearance(body, head_sha)):
                continue  # Exact historical positives neither clear nor add concerns.
            if (kind == "review" and sha and sha != head_sha
                and entry.get("state") == "COMMENTED"
                and re.fullmatch(r"\s*(?:looks good|lgtm)[.!]?\s*", body, re.IGNORECASE)):
                continue  # Historical bare positives neither clear nor raise findings.
            if kind == "comment" and any(
                not head_sha.startswith(bound.lower()) and _bot_review_is_acceptable(candidate, bound)
                for bound in EXPLICIT_SHA_BINDING_RE.findall(body)
            ):
                continue  # Body-bound historical positives are not unresolved findings.
            if (sha and sha != head_sha and _review_login(candidate) == "tessl-reviewer"
                and _tessl_historical_clean_review(candidate)):
                continue  # Authored historical clean text is neutral, not current clearance.
            if sha and sha != head_sha and _bot_review_is_acceptable(candidate, sha):
                continue  # Historical positives are neither findings nor current clearance.
            timestamp = _review_timestamp(entry) if kind == "review" else _comment_timestamp(entry)
            if not body_bound_source and _bot_review_is_acceptable(candidate, head_sha):
                if (entry.get("incremental_completion") or login == "tessl-reviewer"
                    or entry.get("clearance_scope") == "code_only"):
                    continue  # Limited coverage cannot erase earlier untyped concerns.
                clearances.setdefault(login, []).append((timestamp, kind, index))
            elif str(candidate.get("state", "")).upper() == "CHANGES_REQUESTED" or (body.strip() and not _bot_response_is_only_unavailability(body, login=login)):
                concerns.setdefault(login, []).append((timestamp, kind, index))
    outstanding: list[str] = []
    sources = {"review": reviews, "inline": inline, "comment": comments}
    for login, events in concerns.items():
        pending = [(timestamp, kind, index) for timestamp, kind, index in events
                   if not timestamp or not any(
                       not (sources[cleared_kind][cleared_index].get("source") in {"codex_completion_reaction", "coderabbit_completion"}
                            and cleared_at[:19] == timestamp[:19])
                       and (cleared_at > timestamp or (cleared_at == timestamp and cleared_kind == kind and cleared_index > index))
                       for cleared_at, cleared_kind, cleared_index in clearances.get(login, []))]
        if not pending:
            continue
        label = BOT_REVIEWERS[login]
        outstanding.append(label)
        if diagnostics is not None:
            # Describe evidence shape only; arbitrary prose may contain findings.
            # These labels never participate in clearance or acceptance.
            categories = {
                "changes_requested" if kind == "review" and str(sources[kind][index].get("state", "")).upper() == "CHANGES_REQUESTED"
                else "inline_review_comment" if kind == "inline"
                else "unrecognised_verdict_format"
                for _, kind, index in pending
            }
            for _, kind, index in pending:
                categories.update(_review_blocker_shape_hints(login, kind, _review_body(sources[kind][index]), head_sha))
            diagnostics[label] = sorted(categories)
    return sorted(outstanding)


def review_clearance_guidance(head_sha: str, reviewer_names: list[str] | None = None) -> str:
    """Describe a request the caller may make; never send it or grant authority."""
    reviewer_request = (
        "request each outstanding or still-missing required reviewer to inspect the current head"
        if not reviewer_names
        else "request current-head inspection from each outstanding or still-missing "
        f"required reviewer: {', '.join(sorted(set(reviewer_names)))}"
    )
    formal = ("CodeRabbit may supply a verified metadata-only or structured automatic completion, or qualifying formal review evidence; narrative alone cannot clear it. "
              "When inspection already completed, use qualifying formal review evidence, or authenticated pr-repair-endorsement/v1 only where the owning repository supports its protected CI route; "
              "a coordinator-written note or local digest is not an endorsement. Do not repeat completed inspection merely to change wording. "
              if not reviewer_names or "CodeRabbit" in reviewer_names else "")
    return (
        "Inspect the outstanding review sources and resolve any findings first. "
        f"With matching user authorization and execution approval, {reviewer_request}; "
        "do not repeat a reviewer who already provided current-head clearance unless "
        "that reviewer subsequently raised an outstanding concern. "
        f"Review current head {head_sha}; report any remaining findings or publish the normal supported completion result. "
        f"The explicit statement 'No findings for {head_sha}.' is also supported, not required after native completion. "
        "Do not request duplicate clearance when authenticated current-head completion already qualifies. "
        f"{formal}"
        "If the hosted reviewDecision remains CHANGES_REQUESTED, a comment does not clear it: "
        "obtain a formal review update or a separately authorized dismissal that clears that decision. "
        "Then rerun readiness against the current head; all other gates still apply. "
        "A format label is not clearance."
    )


def native_review_diagnostics(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Identify unclassified source sections for inspection; never grant evidence."""
    diagnostics = []
    for entry in entries:
        body = _review_body(entry)
        if (_review_login(entry) != "coderabbitai"
            or not body.startswith("<!-- coderabbit-ai-generated:v1 -->")
            or "<!-- This is an auto-generated comment: summarize by coderabbit.ai -->" not in body):
            continue
        sections = []
        for name in ("review_stack_entry", "walkthrough", "pre_merge_checks_walkthrough",
                     "finishing_touch_checkbox", "review_details", "final_review_risk"):
            parts = re.findall(re.escape(f"<!-- {name}_start -->") + r"(.*?)"
                               + re.escape(f"<!-- {name}_end -->"), body, re.DOTALL)
            if any(part.strip() for part in parts):
                sections.append(name)
        if sections:
            diagnostics.append({"source_url": entry.get("html_url"),
                                "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
                                "unclassified_sections": sections,
                                "status": "requires_independent_adjudication",
                                "qualifies_for_clearance": False})
    return diagnostics


def reviewers_for_clearance(
    concerns: list[str], qualifying: set[str], required_count: int,
    observed_reviewers: set[str] | None = None,
) -> list[str]:
    """Name concern owners, prefer unobserved reviewers, and meet only the quorum."""
    requested = {
        login for login, name in BOT_REVIEWERS.items() if name in concerns
    }
    remaining = max(0, required_count - len((qualifying | requested) & set(REQUIRED_BOT_REVIEWERS)))
    observed = observed_reviewers or set()
    candidates = [
        login for login in REQUIRED_BOT_REVIEWERS
        if login not in qualifying and login not in requested
    ]
    # If one provider already returned an unavailable or invalid response,
    # ask an identity with no evidence first when that alone can fill quorum.
    candidates.sort(key=lambda login: login in observed)
    for login in candidates:
        if remaining == 0:
            break
        requested.add(login)
        remaining -= 1
    return [name for login, name in BOT_REVIEWERS.items() if login in requested]


CODERABBIT_BOT_SEAT_SKIP_TEMPLATE = """<!-- coderabbit-ai-generated:v1 -->

<!-- This is an auto-generated comment: summarize by coderabbit.ai -->
<!-- This is an auto-generated comment: skip review by coderabbit.ai -->

> [!IMPORTANT]
> ## Review skipped
>\x20
> This PR was authored by a bot without an assigned CodeRabbit review seat. Ask an organization administrator to assign a seat to the bot. See the [seat-assignment guide](https://docs.coderabbit.ai/management/seat-assignment). After the seat is assigned, request a review again.
>\x20
> <details>
> <summary><strong><picture><source media="(prefers-color-scheme: dark)" srcset="https://storage.googleapis.com/coderabbit_public_assets/review-comment-icons-v1/cog-dark.svg"><img src="https://storage.googleapis.com/coderabbit_public_assets/review-comment-icons-v1/cog.svg" width="16" height="16" align="absmiddle" alt=""></picture> Run configuration</strong></summary>
> <dl>
> <dd>
>\x20
> - **Source mode**: Auto
> - **Repository**: Unavailable
> - **Branch**: Unavailable
> - **File**: No configuration file from this repository applied
> - **Commit**: Unavailable
> - **Layers**: Organization UI; Enforced overrides: Organization
> - **Review profile**: CHILL
> - **Plan**: Advanced
> - **Run ID**: `{run}`
>\x20
> </dd>
> </dl>
> </details>
>\x20
> You can disable this status message by setting the `reviews.review_status` to `false` in the CodeRabbit configuration file.

<!-- end of auto-generated comment: skip review by coderabbit.ai -->

<!-- autopilot:start -->
- [ ] <!-- {{"checkboxId":"{checkbox}"}} --> <strong title="Keep fixing CodeRabbit findings and required CI, and resolving merge conflicts">Autofix</strong> · Keep fixing CodeRabbit findings and required CI, and resolving merge conflicts
<!-- autopilot:end -->"""


def _bot_response_is_only_unavailability(body: str, *, login: str = "") -> bool:
    """Ignore only standalone service statuses, never finding prose."""
    # Match the complete observed status, including the inert unchecked footer.
    # Only provider-generated run/checkbox UUIDs vary; all narrative is fixed.
    if login == "coderabbitai":
        uuid_pattern = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
        skip_pattern = re.escape(CODERABBIT_BOT_SEAT_SKIP_TEMPLATE.format(run="RUN_UUID", checkbox="CHECKBOX_UUID"))
        skip_pattern = skip_pattern.replace("RUN_UUID", uuid_pattern).replace("CHECKBOX_UUID", uuid_pattern)
        if re.fullmatch(skip_pattern, body):
            return True
    if login == "coderabbitai" and re.fullmatch(
        r"<!-- coderabbit-ai-generated:v1 -->\n\n"
        r"<!-- This is an auto-generated reply by CodeRabbit -->\n"
        r"<!-- CodeRabbit review command invocation: v2:[0-9a-f]{64} -->\n"
        r"<details>\n<summary>Action not completed</summary>\n<dl>\n<dd>\n\n"
        r"Review skipped\.\n\n</dd>\n</dl>\n</details>\n?", body
    ):
        return True
    if login == "chatgpt-codex-connector" and body.strip() in {
        ("Codex usage limits have been reached for code reviews. Please check with the admins of this repo to increase the limits by adding credits.\n"
         "Repo admins can enable using credits for code reviews in their [settings](https://chatgpt.com/codex/cloud/settings/code-review)."),
        "You have reached your Codex usage limits for code reviews. You can see your limits in the [Codex usage dashboard](https://chatgpt.com/codex/cloud/settings/usage).",
    }:
        return True
    return re.fullmatch(
        r"\s*(?:review\s+(?:failed|error)\s*:\s*)?(?:(?:review\s+)?quota\s+(?:exceeded|exhausted)|"
        r"(?:review\s+)?rate[- ]limited|rate\s+limit\s+exceeded|"
        r"review\s+(?:failed|error)|unable\s+to\s+review|error:\s*review\s+unavailable|"
        r"authentication\s+failed(?:\s+while\s+reviewing)?|"
        r"(?:http\s+)?401(?:\s+unauthorized)?|403\s+forbidden|"
        r"resource\s+not\s+accessible\s+by\s+integration|(?:bad|invalid)\s+credentials)"
        r"(?:\s+for\s+[0-9a-f]{7,64})?[.!]?\s*", body, re.IGNORECASE,
    ) is not None


def repair_endorsement_lane(root: Path, pr: dict[str, Any], head: str,
                            reviews: list[dict], inline: list[dict], comments: list[dict],
                            *, require_protected_run: bool = True) -> dict[str, Any]:
    """Use authenticated independent evidence without synthesizing a review."""
    try:
        try:
            from pr_repair_endorsement import (
                MARKER,
                parse_endorsement,
                verify_endorsements,
            )
            from pr_review_risk import committed_review_requirement
        except ModuleNotFoundError as exc:
            if exc.name not in {"pr_repair_endorsement", "pr_review_risk"}:
                raise
            from codex.scripts.pr_repair_endorsement import (
                MARKER,
                parse_endorsement,
                verify_endorsements,
            )
            from codex.scripts.pr_review_risk import committed_review_requirement
        if pr.get("reviewDecision") == "CHANGES_REQUESTED":
            return lane("fail", "active changes-requested decision remains", head_sha=head)
        pr_author_record = pr.get("author")
        if not isinstance(pr_author_record, dict) or not isinstance(pr_author_record.get("login"), str):
            raise TypeError("authenticated PR author is unavailable")
        pr_author = pr_author_record["login"]
        latest_states = {_review_login(review): review.get("state") for review in reviews}
        if "CHANGES_REQUESTED" in latest_states.values():
            return lane("fail", "an independent review still requests changes", head_sha=head)
        slug, error = repository_slug(root)
        if error or not slug:
            raise ValueError(error or "repository identity unavailable")
        host, error = review_repository_host(pr, slug)
        if error or not host:
            raise ValueError(error or "repository host unavailable")
        base = pr.get("baseRefOid")
        if not isinstance(base, str) or not SHA_RE.fullmatch(base):
            raise ValueError("complete committed diff requires the hosted base SHA")
        requirement = committed_review_requirement(changed_file_records(root, base, head))
        required_count = requirement["required_bot_review_count"]
        if type(required_count) is not int or required_count not in {1, 2}:
            raise ValueError("invalid committed-diff review quorum")
        collections = [reviews, inline, comments]
        filtered = []
        for entries in collections:
            kept = []
            for entry in entries:
                body = _review_body(entry)
                if body.startswith(MARKER):
                    if (_review_login(entry) not in REQUIRED_BOT_REVIEWERS
                        or _review_login(entry).casefold() == pr_author.casefold().removesuffix("[bot]")):
                        continue  # Untrusted marker text cannot select or poison repair evidence.
                    parse_endorsement(body)  # Malformed records cannot hide a concern.
                elif body.strip() and not _bot_response_is_only_unavailability(body, login=_review_login(entry)):
                    kept.append(entry)
            filtered.append(kept)
        def resolve_review_tree(review_sha: str) -> str:
            commit_sha = git(root, "rev-parse", f"{review_sha}^{{commit}}")
            if commit_sha != review_sha:
                raise ValueError("formal review SHA does not resolve to itself as a commit")
            return git(root, "rev-parse", f"{review_sha}^{{tree}}")

        def qualifies_for_repair(review: dict[str, Any]) -> bool:
            return (
                _review_login(review) in REQUIRED_BOT_REVIEWERS
                and _review_login(review) != pr_author.casefold().removesuffix("[bot]")
                and review.get("state") in {"COMMENTED", "APPROVED"}
                and SHA_RE.fullmatch(_review_sha(review) or "") is not None
                and bool(_review_body(review).strip())
                and not _review_body(review).startswith(MARKER)
                and not _bot_review_has_blocked_response(_review_body(review), login=_review_login(review))
            )

        sources = clearance_sources(
            *filtered,
            resolve_review_tree=resolve_review_tree,
            qualify_review=qualifies_for_repair,
        )
        sources_by_url = {source["url"]: source for source in sources}
        completed_sources = [
            {**sources_by_url[review["html_url"]], "state": review.get("state"),
             "body": _review_body(review)}
            for review in reviews
            if qualifies_for_repair(review)
            and isinstance(review.get("html_url"), str)
            and review["html_url"] in sources_by_url
        ]
        completed = {source["author"] for source in completed_sources}
        if len(completed) < required_count:
            return lane("fail", "completed independent review coverage is missing",
                        head_sha=head, completed_reviewers=sorted(completed), **requirement)
        def endorsement_git(*args: str) -> str:
            try:
                result = run_command(["git", *args], root)
            except CommandFailure as exc:
                if exc.__cause__ is not None:  # Preserve timeout and OS failures.
                    raise
                raise ValueError(f"Git evidence lookup failed: {args[0]}") from exc
            return result.stdout.strip()

        accepted, gaps = verify_endorsements(
            entries=[entry for collection in collections for entry in collection],
            sources=sources, repository=slug, pr_author=pr_author,
            number=pr["number"], head=head,
            reviewers=set(REQUIRED_BOT_REVIEWERS), git=endorsement_git,
            review_sources=completed_sources, required_review_count=required_count,
        )
        if not accepted:
            return lane("fail", "finding-specific repair evidence is incomplete",
                        head_sha=head, proof_gaps=gaps, **requirement)
        inventory_digest = hashlib.sha256(json.dumps(clearance_sources(*collections),
            sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        ci_evidence = None
        if require_protected_run:
            from pr_repair_ci import protected_report
            ci_evidence = protected_report(repository=slug, number=pr["number"], head=head,
                inventory_digest=inventory_digest,
                command=lambda args: run_command(args, root, timeout=30).stdout)
        # Recheck hosted state after the potentially slow provider requests.
        latest, error = collect_clearance_sources(root, pr["number"], slug, host)
        if error or latest != clearance_sources(*collections):
            raise ValueError(error or "review inventory changed during verification")
        final_pr, error = gh_pr(root, for_export=True, number=pr["number"])
        if error or not final_pr or any(final_pr.get(key) != pr.get(key) for key in
                                       ("number", "url", "author", "headRefOid", "baseRefOid", "state", "reviewDecision")):
            raise ValueError(error or "PR identity or review decision changed during verification")
        final_checks = checks_lane(final_pr, head)
        if final_checks["status"] != "pass":
            raise ValueError(f"required checks changed during verification: {final_checks['evidence']}")
        threads, error = review_threads(root, pr["number"], head)
        if error or threads.get("truncated") or threads.get("unresolved_threads"):
            raise ValueError(error or "review threads changed during verification")
        return lane("pass", "independent endorsement and current-tree repair evidence verified",
                    head_sha=head, review_mode="verified_repair", endorsements=accepted,
                    inventory_digest=inventory_digest, protected_ci=ci_evidence,
                    unresolved_threads=0, **requirement)
    except (ValueError, ImportError, CommandFailure, RecursionError, OSError, KeyError, TypeError) as exc:
        return lane("blocked", f"repair evidence could not be verified: {exc}", head_sha=head)


def review_requirement(root: Path, pr: dict[str, Any], head: str) -> dict[str, Any]:
    try:
        from pr_review_risk import committed_review_requirement
    except ModuleNotFoundError as exc:
        if exc.name != "pr_review_risk":
            raise
        from codex.scripts.pr_review_risk import committed_review_requirement
    base = pr.get("baseRefOid")
    records = changed_file_records(root, base, head) if isinstance(base, str) and SHA_RE.fullmatch(base) else []
    return committed_review_requirement(records)


def _metadata_verification_matches(
    source: dict[str, Any], sources: list[dict[str, Any]], pr: dict[str, Any],
    head_sha: str, review: dict[str, Any],
) -> bool:
    """Require the observed verification envelope and its preceding finding."""
    base = pr.get("baseRefOid")
    if not isinstance(base, str) or not SHA_RE.fullmatch(base):
        return False
    body = _review_body(source).strip()
    prefix = "<details>\n<summary>🧩 Analysis chain</summary>\n\n"
    if body.startswith(prefix):
        analysis, separator, body = body.partition("</details>\n\n")
        # Only the observed fixed source disclosure is decoration. Unknown
        # narrative, tool traces and malformed boundaries require inspection.
        if not separator or analysis != prefix + "Inspected exact candidate.\n\n":
            return False
    expected = (
        r"`@[A-Za-z0-9-]+` Verified the published PR body\. The Validation section lists "
        r"all three exact installed-phase commands with individual \*\*pass\*\* outcomes\. "
        r"It states the wrapper-execution boundary and separates historical results\.\n\n"
        rf"The head `{re.escape(head_sha)}` and base `{re.escape(base)}` identifiers match those you supplied\. This satisfies the metadata finding\. "
        r"Independent review and merge-readiness remain separate gates\.\n\n"
        r"✅ Review thread resolved\.\n\n_You are interacting with an AI system\._\n\n"
        r"<!-- This is an auto-generated reply by CodeRabbit -->"
    )
    if not re.fullmatch(expected, body) or type(source.get("in_reply_to_id")) is not int:
        return False
    parents = [entry for entry in sources if entry.get("id") == source["in_reply_to_id"]]
    if len(parents) != 1:
        return False
    parent = parents[0]
    parent_url = str(pr.get("url")) + f"#discussion_r{source['in_reply_to_id']}"
    finding = "**Record the exact installed-wheel smoke commands and outcomes.**\n\n"
    parent_time, source_time, review_time = (_codex_event_time(entry.get("created_at")) for entry in (parent, source, review))
    if parent_time is None or source_time is None or review_time is None:
        return False
    parent_user, source_user = parent.get("user"), source.get("user")
    return (parent.get("html_url") == parent_url
            and isinstance(parent_user, dict) and isinstance(source_user, dict)
            and parent_user.get("type") == "Bot"
            and type(parent_user.get("id")) is int and parent_user["id"] > 0
            and parent_user.get("id") == source_user.get("id")
            and parent_user.get("login") == source_user.get("login")
            and _review_sha(parent) == head_sha and finding in _review_body(parent)
            and parent_time < source_time <= review_time)


def _independent_inspection_report(body: str) -> bool:
    """A clarification cannot use another clarification as its provenance."""
    try:
        disclosure = json.loads(_coderabbit_reply_statement(body, disclosure_only=True))
    except ValueError:
        return False
    return (isinstance(disclosure, dict) and disclosure.get("source") == ""
            and "The rate-limit notice applied to the separate automated review action." not in body)


def _inspection_provenance_matches(
    root: Path, pr: dict[str, Any], head_sha: str, review: dict[str, Any],
    sources: list[dict[str, Any]],
) -> bool:
    """Bind supported disclosure provenance before it supplies reviewer quorum."""
    body = _review_body(review)
    if _review_login(review) != "coderabbitai" or not _coderabbit_reply_statement(body):
        return True  # Other layouts retain their existing qualification rules.
    try:
        disclosure = json.loads(_coderabbit_reply_statement(body, disclosure_only=True))
    except ValueError:
        return False
    if disclosure == {}:
        return True
    if isinstance(disclosure, dict) and set(disclosure) == {"verification", "statement"}:
        link = disclosure["verification"]
        if (not isinstance(link, str) or disclosure["statement"] != f"No findings for {head_sha}."
            or not re.fullmatch(re.escape(str(pr.get("url"))) + r"#discussion_r[1-9][0-9]*", link)):
            return False
        matches = [entry for entry in sources if entry.get("html_url") == link]
        if len(matches) != 1:
            return False
        source = matches[0]
        author = source.get("user")
        return (isinstance(author, dict) and author.get("type") == "Bot"
                and type(author.get("id")) is int and author["id"] > 0
                and _review_login(source) == "coderabbitai" and _review_sha(source) == head_sha
                and type(source.get("id")) is int
                and source["id"] == int(link.rsplit("discussion_r", 1)[1])
                and _metadata_verification_matches(source, sources, pr, head_sha, review))
    required = {"base", "prior", "count", "source", "statement"}
    if (not isinstance(disclosure, dict) or set(disclosure) not in (required, required | {"paths"})
        or any(not isinstance(value, str) for value in disclosure.values())
        or disclosure["base"] != pr.get("baseRefOid")
        or disclosure["statement"] != f"No findings for {head_sha}."):
        return False
    try:
        records = changed_file_records(root, disclosure["base"], head_sha)
    except (CommandFailure, ValueError):
        return False
    if disclosure["count"] != str(len(records)) or ("paths" in disclosure and
        {record.get("path") for record in records} != set(disclosure["paths"].split(","))):
        return False
    if run_command(["git", "merge-base", "--is-ancestor", disclosure["prior"], head_sha], root, check=False).returncode:
        return False
    link = disclosure["source"]
    if not link:
        return True
    if not re.fullmatch(re.escape(str(pr.get("url"))) + r"#issuecomment-[1-9][0-9]*", link):
        return False
    # A clarification must reference the authenticated full inspection in this
    # complete inventory, not another author's quote or a chained clarification.
    return any(
        entry.get("html_url") == link and _review_login(entry) == "coderabbitai"
        and _independent_inspection_report(_review_body(entry))
        and _bot_review_is_acceptable({**entry, "state": "COMMENTED"}, head_sha)
        and _inspection_provenance_matches(root, pr, head_sha, entry, [])
        for entry in sources
    )


def reviews_lane(root: Path, pr: dict[str, Any], head_sha: str, review_waiver: dict[str, Any] | None = None) -> dict[str, Any]:
    """Evaluate current-head review clearance and return lane status and evidence."""
    reviews = pr.get("reviews")
    if not isinstance(reviews, list):
        return lane("blocked", "hosted PR review data was not returned", head_sha=head_sha)
    current_approvals = []
    unknown_commit = 0
    for review in reviews:
        if not isinstance(review, dict) or str(review.get("state", "")).upper() != "APPROVED":
            continue
        review_sha = _review_sha(review)
        if review_sha == head_sha:
            login = _human_review_login(review)
            if login is not None:
                current_approvals.append(login)
        elif not review_sha:
            unknown_commit += 1
    threads, error = review_threads(root, int(pr["number"]), head_sha)
    if error:
        return lane("blocked", error, head_sha=head_sha, current_head_approvals=current_approvals)
    if threads.get("truncated"):
        return lane("blocked", "review-thread query exceeded its first page", head_sha=head_sha, current_head_approvals=current_approvals)
    unresolved = int(threads.get("unresolved_threads", 0))
    if unresolved:
        return lane("fail", "unresolved review threads remain", head_sha=head_sha, current_head_approvals=current_approvals, unresolved_threads=unresolved)
    approval_mode: str | None = None
    approval_details: dict[str, Any] = {}
    if review_waiver is not None:
        if str(pr.get("reviewDecision", "")).upper() == "CHANGES_REQUESTED":
            return lane("fail", "hosted PR review decision is CHANGES_REQUESTED", head_sha=head_sha, current_head_approvals=current_approvals, unresolved_threads=0, review_waiver=review_waiver)
        authorized_by = str(review_waiver.get("authorized_by") or "").strip().casefold()
        approver_logins = {login.casefold() for login in current_approvals}
        if str(pr.get("reviewDecision", "")).upper() != "APPROVED" or authorized_by not in approver_logins:
            return lane(
                "fail",
                "review waiver requires a matching current-head human APPROVED review",
                head_sha=head_sha,
                current_head_approvals=current_approvals,
                unresolved_threads=0,
                review_waiver=review_waiver,
            )
        approval_mode = "solo_review_waiver"
        approval_details["review_waiver"] = review_waiver
    elif current_approvals:
        if str(pr.get("reviewDecision", "")).upper() != "APPROVED":
            return lane("fail", "hosted PR review decision is not APPROVED", head_sha=head_sha, current_head_approvals=current_approvals, unresolved_threads=0)
        approval_mode = "human_approval"

    bot_reviews = current_head_bot_reviews(reviews, head_sha)
    comments, comment_error = review_comments(root, int(pr["number"]))
    if comment_error:
        return lane("blocked", comment_error, head_sha=head_sha, current_head_approvals=current_approvals, current_head_bot_reviews={}, required_bot_reviewers=REQUIRED_BOT_REVIEWERS, unresolved_threads=0)
    bot_comments = current_head_bot_comments(comments, head_sha)
    issue_entries, issue_error = issue_comments(root, int(pr["number"]))
    if issue_error:
        return lane("blocked", issue_error, head_sha=head_sha, current_head_approvals=current_approvals, current_head_bot_reviews={}, required_bot_reviewers=REQUIRED_BOT_REVIEWERS, unresolved_threads=0)
    authentic_issue_entries = issue_entries
    completion, completion_error = codex_completion_review(root, pr, head_sha, comments, authentic_issue_entries)
    if completion_error:
        return lane("blocked", completion_error, head_sha=head_sha)
    rabbit_completion, completion_error = coderabbit_completion_review(root, pr, head_sha, comments, authentic_issue_entries)
    if completion_error:
        return lane("blocked", completion_error, head_sha=head_sha)
    issue_entries = recorded_review_entries(pr, authentic_issue_entries, head_sha)
    # Chat history never grants clearance; only verified automatic completion
    # or independent formal review evidence may fill CodeRabbit's quorum slot.
    issue_entries = [{**entry, "record_only_reply": True} if _review_login(entry) == "coderabbitai"
                     else entry for entry in issue_entries]
    if rabbit_completion is not None:
        issue_entries = [entry for entry in issue_entries if entry.get("id") != rabbit_completion.get("id")]
        issue_entries.append(rabbit_completion)
    if completion is not None:
        excluded_urls = {completion.get("html_url")}
        code_receipt_url = completion.get("completion_evidence", {}).get("code_receipt_url")
        if isinstance(code_receipt_url, str):
            excluded_urls.add(code_receipt_url)
        issue_entries = [entry for entry in issue_entries if entry.get("html_url") not in excluded_urls]
        issue_entries = [*issue_entries, completion]
    bot_issue_comments = current_head_bot_issue_comments(issue_entries, head_sha)
    for login, completed in (("chatgpt-codex-connector", completion), ("coderabbitai", rabbit_completion)):
        selected = bot_issue_comments.get(login)
        if completed is not None and selected is not None and _bot_response_is_only_unavailability(_review_body(selected), login=login):
            # A later failed request does not undo an independently completed review.
            bot_issue_comments[login] = completed

    if any(_review_login(entry) in BOT_REVIEWERS
           and _review_login(entry).casefold() != _review_login({"user": pr.get("author")}).casefold()
           and _review_body(entry).startswith("pr-repair-endorsement/v1\n")
           for entry in reviews + comments + issue_entries):
        return repair_endorsement_lane(root, pr, head_sha, reviews, comments, authentic_issue_entries)

    reviews = [_join_tessl_review_check(review, pr)
               if _review_login(review) == "tessl-reviewer" else review for review in reviews]
    bot_reviews = {login: (_join_tessl_review_check(review, pr)
                          if login == "tessl-reviewer" else review)
                   for login, review in bot_reviews.items()}
    diagnostics: dict[str, list[str]] = {}
    concerns = outstanding_bot_concerns(reviews, comments, issue_entries, head_sha, diagnostics=diagnostics)
    bot_evidence: dict[str, dict[str, Any]] = {}
    for login in BOT_REVIEWERS:
        review = bot_reviews.get(login)
        comment_candidates: list[dict[str, Any]] = []
        if (comment := bot_comments.get(login)) is not None:
            comment_candidates.append({**comment, "state": "COMMENTED", "source": "inline_review_comment"})
        if (comment := bot_issue_comments.get(login)) is not None:
            comment_candidates.append({**comment, "state": "COMMENTED", "source": "issue_comment"})
        latest_comment: dict[str, Any] | None = None
        for candidate in comment_candidates:
            timestamp = _comment_timestamp(candidate)
            previous_timestamp = _comment_timestamp(latest_comment) if latest_comment else ""
            if _should_replace_timestamped_candidate(latest_comment, timestamp, previous_timestamp):
                latest_comment = candidate
        latest_comment_timestamp = _comment_timestamp(latest_comment) if latest_comment else ""
        if review is None:
            selected = latest_comment
        elif (login == "coderabbitai" and rabbit_completion is not None
              and latest_comment is not None
              and type(rabbit_completion.get("id")) is int and rabbit_completion["id"] > 0
              and latest_comment.get("id") == rabbit_completion.get("id")
              and _review_sha(rabbit_completion) == head_sha
              and _bot_review_is_acceptable(rabbit_completion, head_sha)
              and _review_sha(review) == head_sha
              and review.get("state") == "APPROVED" and _review_body(review) == ""):
            # A blank native approval adds no finding and cannot replace a
            # verified completion with an empty verdict. Keep the original
            # clearance time; all later concerns still pass through below.
            selected = latest_comment
        elif latest_comment is not None:
            review_timestamp = _review_timestamp(review)
            comment_is_blocked = _bot_review_has_blocked_response(str(latest_comment.get("body") or ""), login=_review_login(latest_comment))
            if latest_comment_timestamp > review_timestamp or (
                latest_comment_timestamp == review_timestamp and comment_is_blocked
            ):
                selected = latest_comment
            else:
                selected = review
        else:
            selected = review
        if selected is not None:
            if login == "tessl-reviewer":
                selected = _join_tessl_review_check(selected, pr)
            bot_evidence[login] = selected
    if any(not _inspection_provenance_matches(root, pr, head_sha, review, reviews + comments + issue_entries)
           for review in bot_evidence.values()):
        return lane("fail", "CodeRabbit inspection provenance does not match this PR/base/head or authenticated source",
                    head_sha=head_sha, unresolved_threads=0)
    if approval_mode is not None:
        if concerns:
            detail = "; ".join(
                f"{name}={','.join(categories)}" for name, categories in sorted(diagnostics.items())
            ).replace("changes_requested", "CHANGES_REQUESTED")
            evidence = "bot review evidence requires later explicit clearance: " + detail
            if any(
                "unrecognised_verdict_format" in categories
                for categories in diagnostics.values()
            ):
                evidence += "; unrecognised text may contain findings and requires inspection"
            return lane(
                "fail",
                evidence,
                head_sha=head_sha,
                current_head_approvals=current_approvals,
                outstanding_bot_concerns=concerns,
                review_blocker_categories=diagnostics,
                unresolved_threads=0,
                codex_completion_evidence=completion["completion_evidence"] if completion else None,
                coderabbit_completion_evidence=rabbit_completion["completion_evidence"] if rabbit_completion else None,
                review_source_diagnostics=native_review_diagnostics([
                    entry for entry in authentic_issue_entries
                    if rabbit_completion is None or entry.get("html_url") != rabbit_completion["html_url"]
                ]),
                next_action=review_clearance_guidance(head_sha, concerns),
                **approval_details,
            )
        if approval_mode == "solo_review_waiver":
            return lane(
                "pass",
                "explicit solo-review waiver accepted for missing independent bot approvals",
                head_sha=head_sha,
                current_head_approvals=current_approvals,
                unresolved_threads=0,
                review_mode=approval_mode,
                **approval_details,
            )
        return lane(
            "pass",
            "current-head approval and resolved review threads verified",
            head_sha=head_sha,
            current_head_approvals=current_approvals,
            unresolved_threads=0,
            review_mode=approval_mode,
        )
    try:
        requirement = review_requirement(root, pr, head_sha)
    except (ValueError, CommandFailure) as exc:
        if not concerns:
            return lane("blocked", f"review risk could not be established: {exc}", head_sha=head_sha)
        detail = "; ".join(
            f"{name}={','.join(categories)}" for name, categories in sorted(diagnostics.items())
        ).replace("changes_requested", "CHANGES_REQUESTED")
        concern_reviewers = reviewers_for_clearance(concerns, set(), 0, set(bot_evidence))
        return lane(
            "blocked",
            f"review risk could not be established: {exc}; known bot concerns: {detail}",
            head_sha=head_sha,
            outstanding_bot_concerns=concerns,
            review_blocker_categories=diagnostics,
            next_action=review_clearance_guidance(head_sha, concern_reviewers),
        )
    qualifying = {login for login, review in bot_evidence.items()
                  if login in REQUIRED_BOT_REVIEWERS and _bot_review_is_acceptable(review, head_sha)}
    quorum = len(qualifying) >= requirement["required_bot_review_count"]
    if concerns:
        detail = "; ".join(
            f"{name}={','.join(categories)}" for name, categories in sorted(diagnostics.items())
        ).replace("changes_requested", "CHANGES_REQUESTED")
        evidence = "bot review evidence requires later explicit clearance: " + detail
        if any(
            "unrecognised_verdict_format" in categories
            for categories in diagnostics.values()
        ):
            evidence += "; unrecognised text may contain findings and requires inspection"

        reviewer_names = reviewers_for_clearance(
            concerns, qualifying, requirement["required_bot_review_count"], set(bot_evidence)
        )

        return lane("fail", evidence,
                    head_sha=head_sha, outstanding_bot_concerns=concerns, unresolved_threads=0,
                    review_blocker_categories=diagnostics,
                    codex_completion_evidence=completion["completion_evidence"] if completion else None,
                    coderabbit_completion_evidence=rabbit_completion["completion_evidence"] if rabbit_completion else None,
                    review_source_diagnostics=native_review_diagnostics([
                        entry for entry in authentic_issue_entries
                        if rabbit_completion is None or entry.get("html_url") != rabbit_completion["html_url"]]),
                    next_action=review_clearance_guidance(head_sha, reviewer_names))
    missing = sorted(set(REQUIRED_BOT_REVIEWERS) - set(bot_evidence))
    if missing and not quorum:
        labels = ", ".join(BOT_REVIEWERS[login] for login in sorted(set(REQUIRED_BOT_REVIEWERS) - qualifying))
        reason = f"no current-head explicit no-findings bot review for: {labels}"
        if unknown_commit:
            reason += "; hosted review records omitted commit identity"
        missing_reviewers = reviewers_for_clearance(
            concerns, qualifying, requirement["required_bot_review_count"], set(bot_evidence)
        )
        return lane("fail", reason, next_action=review_clearance_guidance(head_sha, missing_reviewers), head_sha=head_sha, current_head_approvals=[], current_head_bot_reviews={}, current_head_bot_comments=sorted(bot_comments), required_bot_reviewers=REQUIRED_BOT_REVIEWERS, unresolved_threads=0)
    invalid = {
        BOT_REVIEWERS[login]: str(review.get("state", "")).upper() or "UNKNOWN"
        for login, review in bot_evidence.items()
        if not _bot_review_is_acceptable(review, head_sha)
    }
    bot_state_details = {login: str(review.get("state", "")).upper() for login, review in bot_evidence.items()}
    if invalid and not quorum:
        detail = ", ".join(f"{name}={state or 'UNKNOWN'}" for name, state in sorted(invalid.items()))
        missing_reviewers = reviewers_for_clearance(
            concerns, qualifying, requirement["required_bot_review_count"], set(bot_evidence)
        )
        return lane("fail", f"current-head bot review lacks explicit no-findings evidence or is blocked: {detail}", next_action=review_clearance_guidance(head_sha, missing_reviewers), head_sha=head_sha, current_head_approvals=[], current_head_bot_reviews=bot_state_details, current_head_bot_comments=sorted(bot_comments), current_head_bot_issue_comments=sorted(bot_issue_comments), required_bot_reviewers=REQUIRED_BOT_REVIEWERS, unresolved_threads=0)
    if str(pr.get("reviewDecision", "")).upper() == "CHANGES_REQUESTED":
        return lane("fail", "hosted PR review decision is CHANGES_REQUESTED", next_action=review_clearance_guidance(head_sha), head_sha=head_sha, current_head_approvals=[], current_head_bot_reviews=bot_state_details, current_head_bot_comments=sorted(bot_comments), current_head_bot_issue_comments=sorted(bot_issue_comments), required_bot_reviewers=REQUIRED_BOT_REVIEWERS, unresolved_threads=0)
    return lane(
        "pass",
        "current-head independent bot quorum and resolved review threads verified",
        head_sha=head_sha,
        current_head_approvals=[],
        current_head_bot_reviews=bot_state_details,
        current_head_bot_comments=sorted(bot_comments),
        current_head_bot_issue_comments=sorted(bot_issue_comments),
        codex_completion_evidence=completion["completion_evidence"] if completion else None,
        coderabbit_completion_evidence=rabbit_completion["completion_evidence"] if rabbit_completion else None,
        required_bot_reviewers=REQUIRED_BOT_REVIEWERS,
        unresolved_threads=0,
        review_mode="bot_quorum",
        **requirement,
    )


def review_inspection_authority() -> dict[str, Any]:
    return {
        "allowed_mutations": ["review_request_comment"],
        "prohibited_mutations": ["source_update", "pr_body_update", "review_submission",
                                 "review_thread_reply", "review_thread_resolve", "approval", "merge"],
        "acceptance_claims_proven": False,
    }


def review_inspection_lane(root: Path, pr: dict[str, Any], head_sha: str) -> dict[str, Any]:
    """Request independent inspection without pretending it already cleared."""
    fresh, error = gh_pr(root, number=int(pr["number"]), for_export=True)
    if error or not fresh or fresh.get("state") != "OPEN" or fresh.get("headRefOid") != head_sha or fresh.get("url") != pr.get("url"):
        return lane("blocked", error or "inspection requires an open PR with matching identity and head")
    return lane("pass", "inspection-only request admitted; review readiness is not proven",
                head_sha=head_sha, **review_inspection_authority())


def review_reconciliation_lane(root: Path, pr: dict[str, Any], head_sha: str) -> dict[str, Any]:
    """Admit thread-only reconciliation without asserting final review readiness."""
    threads, error = review_threads(root, int(pr["number"]), head_sha)
    if error:
        return lane("blocked", error, head_sha=head_sha)
    if threads.get("truncated"):
        return lane("blocked", "review-thread query exceeded its first page", head_sha=head_sha)
    unresolved = int(threads.get("unresolved_threads", 0))
    if unresolved <= 0:
        return lane(
            "blocked",
            "review reconciliation requires at least one unresolved thread",
            head_sha=head_sha,
            unresolved_threads=0,
        )
    return lane(
        "pass",
        f"{unresolved} unresolved review thread(s) admitted for evidence-backed reconciliation only",
        head_sha=head_sha,
        unresolved_threads=unresolved,
        unresolved_thread_ids=threads.get("unresolved_thread_ids", []),
        allowed_mutations=["review_thread_reply", "review_thread_resolve"],
        prohibited_mutations=[
            "source_update",
            "pr_body_update",
            "review_submission",
            "approval",
            "merge",
        ],
        acceptance_claims_proven=False,
    )


def default_receipt(root: Path, git_dir: str) -> Path:
    path = Path(git_dir)
    if not path.is_absolute():
        path = (root / path).resolve()
    return _scope.policy_repository_receipt(root, path / "pr-readiness.v1.json")


def build_result(args: argparse.Namespace) -> dict[str, Any]:
    root = resolve_root(args.repo_root)
    branch, head_sha, inferred_base, git_dir, _common_dir = current_worktree(root)
    base_branch = args.base or inferred_base
    base_sha = git(root, "rev-parse", f"refs/remotes/{args.remote}/{base_branch}", check=False) or git(root, "rev-parse", base_branch, check=False)
    if not SHA_RE.fullmatch(base_sha):
        raise CommandFailure(["git", "rev-parse", base_branch], f"base branch could not be resolved: {base_branch}")
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "blocked",
        "phase": args.phase,
        "checked_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "repo": {"root": str(root), "branch": branch, "head_sha": head_sha, "base_branch": base_branch, "base_sha": base_sha, "remote": args.remote},
        "lanes": {},
        "blockers": [],
        "evidence_refs": [f"git:{root}", f"head:{head_sha}"],
    }
    if args.phase == "review_reconciliation":
        result["authority"] = {
            "allowed_mutations": ["review_thread_reply", "review_thread_resolve"],
            "prohibited_mutations": [
                "source_update",
                "pr_body_update",
                "review_submission",
                "approval",
                "merge",
            ],
            "acceptance_claims_proven": False,
        }
    elif args.phase == "review_inspection":
        result["authority"] = review_inspection_authority()
    remote_base = remote_sha(root, args.remote, base_branch)
    remote_head = remote_sha(root, args.remote, branch) if branch != "(detached)" else None
    result["repo"]["remote_base_sha"] = remote_base
    result["repo"]["remote_head_sha"] = remote_head
    if remote_base is None:
        result["lanes"]["remote_ancestry"] = lane("blocked", f"remote base {args.remote}/{base_branch} could not be read")
        result["blockers"].append(blocker(
            "remote_base_unavailable",
            "the hosted repository did not return the current remote base",
        ))
    elif remote_head != head_sha:
        result["lanes"]["remote_ancestry"] = lane("fail", "remote branch does not point at the current local HEAD", remote_base_sha=remote_base, remote_head_sha=remote_head, head_sha=head_sha)
        result["blockers"].append(blocker("remote_head_drift", "push the current commit before creating or updating the PR"))
    elif run_command(["git", "merge-base", "--is-ancestor", remote_base, head_sha], root, check=False).returncode != 0:
        result["lanes"]["remote_ancestry"] = lane("fail", "current HEAD is not descended from the remote base", remote_base_sha=remote_base, head_sha=head_sha)
        result["blockers"].append(blocker("remote_base_drift", "rebase or merge the current remote base in a separate clean lane"))
    else:
        result["lanes"]["remote_ancestry"] = lane("pass", "remote base and branch ancestry match current HEAD", remote_base_sha=remote_base, remote_head_sha=remote_head, head_sha=head_sha)
    dirty = dirty_lane(root)
    result["lanes"]["dirty_worktree"] = dirty
    if dirty["status"] != "pass":
        result["blockers"].append(blocker("dirty_worktree", dirty["evidence"]))
    boundary = worktree_lane(root)
    result["lanes"]["worktree_boundary"] = boundary
    if boundary["status"] != "pass":
        result["blockers"].append(blocker("worktree_boundary", boundary["evidence"]))
    if not args.scope_file:
        result["lanes"]["scope"] = lane("blocked", "an explicit --scope-file is required", changed_paths=[])
        result["blockers"].append(blocker("scope_required", "declare the intended PR paths in a repository-relative scope file"))
    else:
        scope, digest_or_error = parse_scope(args.scope_file.expanduser().resolve(), root)
        if is_scope_digest(digest_or_error):
            changed = changed_paths(root, base_sha, head_sha)
            undeclared = sorted(set(changed) - set(scope))
            if undeclared:
                result["lanes"]["scope"] = lane("fail", "changed paths are outside the declared PR scope", changed_paths=changed, undeclared=undeclared, scope_digest=digest_or_error)
                result["blockers"].append(blocker("scope_mismatch", ", ".join(undeclared)))
            else:
                result["lanes"]["scope"] = lane("pass", "all committed PR paths are declared in the scope file", changed_paths=changed, declared_paths=scope, scope_digest=digest_or_error)
        else:
            result["lanes"]["scope"] = lane("blocked", digest_or_error)
            result["blockers"].append(blocker("scope_invalid", digest_or_error))
    pr, pr_error = gh_pr(root)
    if pr_error:
        result["lanes"]["pull_request"] = lane("blocked", pr_error)
        result["blockers"].append(blocker("hosted_pr_unavailable", pr_error))
    elif args.phase == "create" and pr is not None:
        result["lanes"]["pull_request"] = lane("fail", "a pull request already exists for the current branch", number=pr.get("number"), url=pr.get("url"))
        result["blockers"].append(blocker("pr_already_exists", str(pr.get("url") or pr.get("number"))))
    elif args.phase == "create":
        result["lanes"]["pull_request"] = lane("pass", "no existing pull request found for the current branch")
    elif pr is None:
        result["lanes"]["pull_request"] = lane("fail", "update phase requires an existing pull request")
        result["blockers"].append(blocker("pr_missing", "create the PR only after the create phase passes"))
    else:
        if pr.get("baseRefName") != base_branch:
            result["lanes"]["pull_request"] = lane(
                "fail",
                "hosted PR base branch does not match the receipt base",
                number=pr.get("number"),
                pr_base_branch=pr.get("baseRefName"),
                base_branch=base_branch,
            )
            result["blockers"].append(
                blocker("pr_base_mismatch", "change the PR base to the receipt base branch")
            )
        elif pr.get("baseRefOid") != remote_base:
            result["lanes"]["pull_request"] = lane(
                "fail",
                "hosted PR base commit does not match the current remote base",
                number=pr.get("number"),
                pr_base_sha=pr.get("baseRefOid"),
                remote_base_sha=remote_base,
            )
            result["blockers"].append(
                blocker("pr_base_stale", "refresh the PR after the remote base changes")
            )
        elif pr.get("headRefOid") != head_sha:
            result["lanes"]["pull_request"] = lane("fail", "hosted PR head is stale", pr_head_sha=pr.get("headRefOid"), head_sha=head_sha, number=pr.get("number"))
            result["blockers"].append(blocker("pr_head_stale", "push the current HEAD and refresh hosted review/check state"))
        else:
            result["lanes"]["pull_request"] = lane("pass", "hosted PR head and base match the current checkout", number=pr.get("number"), url=pr.get("url"), head_sha=head_sha)
    result["lanes"]["required_checks"] = lane("not_applicable", "checks are evaluated after a PR exists") if args.phase == "create" or pr is None else phase_checks_lane(pr, head_sha, args.phase)
    review_waiver = None
    review_waiver_error = None
    if args.review_waiver_file and args.phase != "update":
        review_waiver_error = "a review waiver applies only to the update phase"
    elif args.phase == "update" and pr is not None and args.review_waiver_file:
        review_waiver, review_waiver_error = load_review_waiver(
            args.review_waiver_file.expanduser().absolute(), int(pr["number"]), head_sha, root
        )
    if args.phase == "create" or pr is None:
        result["lanes"]["reviews"] = lane("not_applicable", "reviews are evaluated after a PR exists")
    elif args.phase == "review_reconciliation":
        result["lanes"]["reviews"] = review_reconciliation_lane(root, pr, head_sha)
    elif args.phase == "review_inspection" and not review_waiver_error:
        result["lanes"]["reviews"] = review_inspection_lane(root, pr, head_sha)
    elif review_waiver_error:
        result["lanes"]["reviews"] = lane("blocked", review_waiver_error, head_sha=head_sha)
    else:
        result["lanes"]["reviews"] = reviews_lane(root, pr, head_sha, review_waiver)
    for name, value in result["lanes"].items():
        if value["status"] in {"fail", "blocked"} and not any(item["reason"] == value["evidence"] for item in result["blockers"]):
            result["blockers"].append(blocker(name, value["evidence"]))
    statuses = [value["status"] for value in result["lanes"].values()]
    result["status"] = "fail" if "fail" in statuses else "blocked" if "blocked" in statuses else "pass"
    digest = result["lanes"].get("scope", {}).get("details", {}).get("scope_digest", "")
    result["receipt"] = {"path": str(default_receipt(root, git_dir)), "scope_digest": digest}
    return result


def recheck_hosted_state(
    root: Path,
    phase: str,
    head_sha: str,
    *,
    expected_pr: int | None = None,
    expected_repo: str | None = None,
    base_branch: str | None = None,
    base_sha: str | None = None,
    review_waiver_record: dict[str, Any] | None = None,
    expected_thread_id: str | None = None,
    expected_pr_url: str | None = None,
    expected_check_policy_digest: str | None = None,
) -> str | None:
    """Re-read hosted PR state when a receipt is consumed, including update receipts."""
    if phase == "create":
        pr, pr_error = gh_pr(root)
        if pr_error:
            return f"hosted PR state could not be rechecked: {pr_error}"
        return "a pull request now exists for the create-phase receipt" if pr is not None else None
    if type(expected_pr) is not int or expected_pr <= 0:
        return "non-create receipt recheck requires an explicit PR number"
    if not isinstance(expected_repo, str) or not expected_repo:
        return "non-create receipt recheck requires an explicit repository"
    if not isinstance(expected_pr_url, str) or not expected_pr_url:
        return "non-create receipt recheck requires a recorded PR URL"
    pr, pr_error = gh_pr(root, number=expected_pr)
    if pr_error:
        return f"hosted PR state could not be rechecked: {pr_error}"
    if pr is None:
        return "update-phase receipt requires an existing pull request"
    if pr.get("number") != expected_pr:
        return "hosted PR number changed after the receipt was written"
    if pr.get("url") != expected_pr_url:
        return "hosted PR URL changed after the receipt was written"
    _hostname, identity_error = review_repository_host(pr, expected_repo)
    if identity_error:
        return f"hosted PR repository identity is invalid: {identity_error}"
    if base_branch is not None and pr.get("baseRefName") != base_branch:
        return "hosted PR base branch changed after the receipt was written"
    if base_sha is not None and pr.get("baseRefOid") != base_sha:
        return "hosted PR base commit changed after the receipt was written"
    if pr.get("headRefOid") != head_sha:
        return "hosted PR head changed after the receipt was written"
    review_waiver = None
    if review_waiver_record is not None:
        review_waiver, waiver_error = validate_review_waiver_record(review_waiver_record, int(pr["number"]), head_sha, root)
        if waiver_error:
            return waiver_error
    checks = phase_checks_lane(pr, head_sha, phase)
    current_policy_digest = checks.get("details", {}).get("policy_digest")
    if (
        expected_check_policy_digest is not None
        and current_policy_digest != expected_check_policy_digest
    ):
        return "required-check policy changed after the receipt was written"
    if checks["status"] != "pass":
        return f"hosted checks changed after the receipt was written: {checks['evidence']}"
    if phase == "review_inspection":
        inspection = review_inspection_lane(root, pr, head_sha)
        return None if inspection["status"] == "pass" else inspection["evidence"]
    if phase == "review_reconciliation":
        reconciliation = review_reconciliation_lane(root, pr, head_sha)
        if reconciliation["status"] != "pass":
            return f"hosted review reconciliation state changed after the receipt was written: {reconciliation['evidence']}"
        current_thread_ids = reconciliation.get("details", {}).get(
            "unresolved_thread_ids", []
        )
        if expected_thread_id and expected_thread_id not in current_thread_ids:
            return "target review thread is no longer unresolved"
        return None
    reviews = reviews_lane(root, pr, head_sha, review_waiver)
    if reviews["status"] != "pass":
        return f"hosted reviews changed after the receipt was written: {reviews['evidence']}"
    return None


def validate_command_target(
    payload: dict[str, Any],
    *,
    repository: str,
    expected_repo: str | None,
    expected_pr: int | None,
    expected_thread_id: str | None,
    expected_base: str | None = None,
    expected_head: str | None = None,
) -> str | None:
    """Bind a consuming mutation to the repository, PR, and review thread in the receipt."""
    if expected_repo and expected_repo.casefold() != repository.casefold():
        return f"command repository target does not match receipt repository: {expected_repo} != {repository}"
    receipt_repo = payload.get("repo", {})
    if not isinstance(receipt_repo, dict):
        return "receipt repository details are malformed"
    if expected_base and expected_base != receipt_repo.get("base_branch"):
        return f"command base target does not match receipt base: {expected_base} != {receipt_repo.get('base_branch')}"
    if expected_head and expected_head != receipt_repo.get("branch"):
        return f"command head target does not match receipt branch: {expected_head} != {receipt_repo.get('branch')}"
    pull_request_details = payload.get("lanes", {}).get("pull_request", {}).get("details", {})
    receipt_pr_number = pull_request_details.get("number") if isinstance(pull_request_details, dict) else None
    if expected_pr is not None:
        if type(expected_pr) is not int or expected_pr <= 0:
            return "command PR target is invalid"
        if type(receipt_pr_number) is not int or receipt_pr_number != expected_pr:
            return f"command PR target does not match receipt PR: {expected_pr} != {receipt_pr_number}"
    if expected_thread_id:
        reconciliation_details = payload.get("lanes", {}).get("reviews", {}).get("details", {})
        allowed_thread_ids = (
            reconciliation_details.get("unresolved_thread_ids", [])
            if isinstance(reconciliation_details, dict)
            else []
        )
        if expected_thread_id not in allowed_thread_ids:
            return "command review-thread target is not admitted by the reconciliation receipt"
    return None


def validate_receipt_schema(payload: Any) -> str | None:
    """Validate the complete persisted receipt shape before it affects commands."""
    if not isinstance(payload, dict):
        return "receipt must be a JSON object"
    phase = payload.get("phase")
    if phase not in PHASES:
        return "receipt phase is invalid"
    expected_fields = {
        "schema_version",
        "status",
        "phase",
        "checked_at",
        "repo",
        "lanes",
        "blockers",
        "evidence_refs",
        "receipt",
    }
    if phase in {"review_inspection", "review_reconciliation"}:
        expected_fields.add("authority")
    if set(payload) != expected_fields:
        return "receipt must contain exactly the required fields"
    if payload.get("schema_version") != SCHEMA_VERSION:
        return "receipt schema_version is not pr-readiness/v1"
    status = payload.get("status")
    if not isinstance(status, str) or status not in {"pass", "fail", "blocked"}:
        return "receipt status is invalid"
    if not isinstance(payload.get("checked_at"), str) or not payload["checked_at"]:
        return "receipt checked_at is invalid"

    receipt_repo = payload.get("repo")
    repo_fields = {
        "root",
        "branch",
        "head_sha",
        "base_branch",
        "base_sha",
        "remote",
        "remote_base_sha",
        "remote_head_sha",
    }
    if not isinstance(receipt_repo, dict) or set(receipt_repo) != repo_fields:
        return "receipt repository details are malformed"
    for field in ("root", "branch", "base_branch"):
        if not isinstance(receipt_repo.get(field), str) or not receipt_repo[field]:
            return f"receipt repository {field} is invalid"
    for field in ("head_sha", "base_sha"):
        value = receipt_repo.get(field)
        if not isinstance(value, str) or SHA_RE.fullmatch(value) is None:
            return f"receipt repository {field} is not a full commit SHA"
    for field in ("remote_base_sha", "remote_head_sha"):
        value = receipt_repo.get(field)
        if value is not None and (not isinstance(value, str) or SHA_RE.fullmatch(value) is None):
            return f"receipt repository {field} is invalid"
        if status == "pass" and value is None:
            return f"receipt repository {field} is not a full commit SHA"
    if receipt_repo.get("remote") != TRUSTED_REMOTE:
        return f"receipt repository remote must be {TRUSTED_REMOTE}"

    lanes = payload.get("lanes")
    if not isinstance(lanes, dict) or set(lanes) != set(RECEIPT_LANES):
        return "receipt lanes are malformed"
    for name in RECEIPT_LANES:
        lane_value = lanes[name]
        if (not isinstance(lane_value, dict)
                or not {"status", "evidence"} <= set(lane_value)
                <= {"status", "evidence", "details"}):
            return f"receipt lane {name} is malformed"
        lane_status = lane_value.get("status")
        if (not isinstance(lane_status, str)
                or lane_status not in {"pass", "fail", "blocked", "not_applicable"}):
            return f"receipt lane {name} status is invalid"
        if not isinstance(lane_value.get("evidence"), str) or not lane_value["evidence"]:
            return f"receipt lane {name} evidence is invalid"
        if "details" in lane_value and not isinstance(lane_value["details"], dict):
            return f"receipt lane {name} details are malformed"
    scope_details = lanes["scope"].get("details")
    declared_paths = scope_details.get("declared_paths") if isinstance(scope_details, dict) else None
    if (not isinstance(declared_paths, list)
            or any(not isinstance(item, str) or not item for item in declared_paths)
            or declared_paths != sorted(set(declared_paths))):
        return "receipt declared scope paths are malformed"

    blockers = payload.get("blockers")
    if not isinstance(blockers, list):
        return "receipt blockers are malformed"
    for item in blockers:
        if (not isinstance(item, dict) or set(item) != {"code", "reason"}
                or any(not isinstance(item.get(field), str) or not item[field]
                       for field in ("code", "reason"))):
            return "receipt blocker is malformed"
    evidence_refs = payload.get("evidence_refs")
    if (not isinstance(evidence_refs, list)
            or any(not isinstance(item, str) or not item for item in evidence_refs)):
        return "receipt evidence references are malformed"

    receipt = payload.get("receipt")
    if (not isinstance(receipt, dict) or set(receipt) != {"path", "scope_digest"}
            or not isinstance(receipt.get("path"), str) or not receipt["path"]
            or not isinstance(receipt.get("scope_digest"), str)
            or SCOPE_DIGEST_RE.fullmatch(receipt["scope_digest"]) is None):
        return "receipt publication details are malformed"
    if phase == "review_inspection":
        if payload.get("authority") != review_inspection_authority():
            return "inspection receipt authority is malformed"
    elif phase == "review_reconciliation":
        expected_authority = {
            "allowed_mutations": ["review_thread_reply", "review_thread_resolve"],
            "prohibited_mutations": [
                "source_update",
                "pr_body_update",
                "review_submission",
                "approval",
                "merge",
            ],
            "acceptance_claims_proven": False,
        }
        if payload.get("authority") != expected_authority:
            return "reconciliation receipt authority is malformed"
    return None


def validate_receipt(path: Path, args: argparse.Namespace) -> tuple[dict[str, Any], str | None]:
    try:
        payload = json.loads(_scope.policy_repository_read(args.repo_root or Path.cwd(), path))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, f"receipt could not be read: {exc}"
    schema_error = validate_receipt_schema(payload)
    if schema_error:
        return {}, schema_error
    if args.remote != TRUSTED_REMOTE:
        return {}, f"receipt checks require the trusted {TRUSTED_REMOTE} remote"
    if payload.get("status") != "pass":
        return {}, f"receipt status is {payload.get('status')!r}"
    root = resolve_root(args.repo_root)
    branch, head_sha, inferred_base, _git_dir, _common = current_worktree(root)
    base_branch = args.base or inferred_base
    receipt_repo = payload.get("repo", {})
    checks = [("phase", payload.get("phase"), args.phase), ("branch", receipt_repo.get("branch"), branch), ("head_sha", receipt_repo.get("head_sha"), head_sha), ("base_branch", receipt_repo.get("base_branch"), base_branch)]
    for field, actual, expected in checks:
        if actual != expected:
            return {}, f"receipt is stale for {field}: expected {expected}, got {actual}"
    slug, slug_error = repository_slug(root)
    if slug_error or not slug:
        return {}, slug_error or "repository slug unavailable while validating receipt target"
    if args.phase in {"review_inspection", "update"} and args.expected_pr is None:
        return {}, f"{args.phase} receipt consumption requires an explicit command PR target"
    target_error = validate_command_target(
        payload,
        repository=slug,
        expected_repo=args.expected_repo,
        expected_pr=args.expected_pr,
        expected_thread_id=args.expected_thread_id,
        expected_base=args.expected_base,
        expected_head=args.expected_head,
    )
    if target_error:
        return {}, target_error
    age = datetime.now(UTC).timestamp() - path.stat().st_mtime
    if age > args.max_receipt_age:
        return {}, f"receipt is older than {args.max_receipt_age} seconds"
    if not SHA_RE.fullmatch(head_sha):
        return {}, "current HEAD is not a full commit SHA"
    dirty = dirty_lane(root)
    if dirty["status"] != "pass":
        return {}, "worktree became dirty after the receipt was written"
    boundary = worktree_lane(root)
    if boundary["status"] != "pass":
        return {}, "current checkout is no longer a registered worktree"
    remote_base = hosted_remote_sha(root, slug, base_branch)
    remote_head = hosted_remote_sha(root, slug, branch)
    if remote_base != receipt_repo.get("remote_base_sha") or remote_head != receipt_repo.get("remote_head_sha"):
        return {}, "remote ancestry changed after the receipt was written"
    scope_details = payload.get("lanes", {}).get("scope", {}).get("details", {})
    declared_paths = scope_details.get("declared_paths")
    if not isinstance(declared_paths, list):
        return {}, "receipt does not contain declared scope paths"
    current_changed = changed_paths(root, str(receipt_repo.get("base_sha")), head_sha)
    undeclared = sorted(set(current_changed) - set(declared_paths))
    if undeclared:
        return {}, f"current changes escaped the recorded scope: {', '.join(undeclared)}"
    expected_digest = hashlib.sha256(("\n".join(sorted(set(declared_paths))) + "\n").encode("utf-8")).hexdigest()
    if expected_digest != payload.get("receipt", {}).get("scope_digest"):
        return {}, "receipt scope digest does not match its declared paths"
    review_waiver_record = None
    if args.phase == "update":
        review_details = payload.get("lanes", {}).get("reviews", {}).get("details", {})
        if isinstance(review_details, dict) and isinstance(review_details.get("review_waiver"), dict):
            review_waiver_record = review_details["review_waiver"]
    pull_request_details = payload.get("lanes", {}).get("pull_request", {}).get("details", {})
    receipt_pr_number = pull_request_details.get("number") if isinstance(pull_request_details, dict) else None
    recorded_pr_url = pull_request_details.get("url") if isinstance(pull_request_details, dict) else None
    if args.phase != "create":
        if type(receipt_pr_number) is not int or receipt_pr_number <= 0:
            return {}, "non-create receipt does not record a valid PR number"
        if not isinstance(recorded_pr_url, str) or not recorded_pr_url:
            return {}, "non-create receipt does not record its PR URL"
    recheck_pr_number = (
        args.expected_pr if args.expected_pr is not None else receipt_pr_number
    )
    expected_check_policy_digest = None
    if args.phase in {"update", "review_reconciliation"}:
        check_details = payload.get("lanes", {}).get("required_checks", {}).get("details", {})
        if not isinstance(check_details, dict):
            return {}, "receipt required-check details are malformed"
        expected_check_policy_digest = check_details.get("policy_digest")
        if (
            not isinstance(expected_check_policy_digest, str)
            or not SCOPE_DIGEST_RE.fullmatch(expected_check_policy_digest)
        ):
            return {}, "receipt does not bind an authenticated required-check policy"
    hosted_error = recheck_hosted_state(
        root,
        args.phase,
        head_sha,
        expected_pr=recheck_pr_number,
        expected_repo=slug,
        base_branch=str(receipt_repo.get("base_branch")),
        base_sha=str(receipt_repo.get("remote_base_sha")),
        review_waiver_record=review_waiver_record,
        expected_thread_id=args.expected_thread_id,
        expected_pr_url=recorded_pr_url,
        expected_check_policy_digest=expected_check_policy_digest,
    )
    if hosted_error:
        return {}, hosted_error
    return payload, None


def _lifecycle_request(root: Path, repo: str, number: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read one explicitly addressed GitHub PR, never infer a branch's PR."""
    response = run_command(['gh', 'api', '--hostname', 'github.com',
                            f'repos/{repo}/pulls/{number}'], root, check=False)
    if response.returncode:
        raise ValueError('Lifecycle target inventory unavailable')
    value = json.loads(response.stdout)
    expected_url = f'https://github.com/{repo}/pull/{number}'
    if (not isinstance(value, dict) or type(value.get('number')) is not int
            or value['number'] != number or value.get('html_url') != expected_url
            or value.get('state') not in {'open', 'closed'} or type(value.get('draft')) is not bool
            or not isinstance(value.get('node_id'), str) or not value['node_id']
            or len(value['node_id']) > 256):
        raise ValueError('Lifecycle target identity is malformed')
    head, base = value.get('head'), value.get('base')
    if (not isinstance(head, dict) or not isinstance(base, dict)
            or not isinstance(head.get('sha'), str) or not SHA_RE.fullmatch(head['sha'])
            or not isinstance(base.get('sha'), str) or not SHA_RE.fullmatch(base['sha'])
            or not isinstance(base.get('ref'), str) or not base['ref']
            or base.get('repo', {}).get('full_name') != repo):
        raise ValueError('Lifecycle head, base or repository is malformed')
    target = {'number': number, 'url': expected_url, 'node_id': value['node_id'],
              'head': head['sha'], 'base': base['ref'], 'base_sha': base['sha'],
              'state': value['state'], 'draft': value['draft'], 'merged_at': value.get('merged_at')}
    return target, value


def _lifecycle_local_context(root: Path, args: argparse.Namespace) -> dict[str, Any]:
    branch, head, _base, _git_dir, _common = current_worktree(root)
    if dirty_lane(root)['status'] != 'pass' or worktree_lane(root)['status'] != 'pass':
        raise ValueError('Lifecycle production requires a clean registered checkout')
    if args.scope_file is None:
        raise ValueError('Lifecycle operations require an explicit repository-relative scope')
    scope, digest = parse_scope(args.scope_file, root)
    if not is_scope_digest(digest):
        raise ValueError('Lifecycle scope is unavailable or malformed')
    return {'root': str(root), 'branch': branch, 'head': head,
            'scope_digest': digest, 'declared_paths': scope}


def _lifecycle_origin_matches(root: Path, repo: str) -> bool:
    # gh may prefer a GitHub upstream over the checkout's origin.
    origin = run_command(['git', 'remote', 'get-url', TRUSTED_REMOTE], root, check=False)
    if origin.returncode:
        return False
    match = re.fullmatch(
        r'(?:https?://github\.com(?::443)?/|ssh://git@github\.com(?::22)?/|git@github\.com:)'
        r'([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/?',
        origin.stdout.rstrip('\n'),
        re.IGNORECASE,
    )
    return match is not None and match[1].removesuffix('.git').casefold() == repo.casefold()


def _lifecycle_snapshot(root: Path, args: argparse.Namespace) -> dict[str, Any]:
    if (type(args.expected_pr) is not int or args.expected_pr <= 0
            or not isinstance(args.lifecycle_head, str) or not SHA_RE.fullmatch(args.lifecycle_head)
            or os.environ.get('GH_REPO') or os.environ.get('GH_HOST')
            or not isinstance(args.expected_repo, str)
            or not _lifecycle_origin_matches(root, args.expected_repo)):
        raise ValueError('Lifecycle operations need an explicit unchanged repository, PR and head')
    repo, error = repository_slug(root, required_host='github.com')
    if error or not repo or repo != args.expected_repo:
        raise ValueError('Lifecycle operations need an explicit unchanged repository, PR and head')
    target, raw = _lifecycle_request(root, repo, args.expected_pr)
    if target['head'] != args.lifecycle_head or (args.base and args.base != target['base']):
        raise ValueError('Lifecycle target head or base changed')
    replacement = None
    if args.lifecycle == 'close':
        if type(args.replacement_pr) is not int or args.replacement_pr <= 0 or args.replacement_pr == args.expected_pr:
            raise ValueError('Supersession close requires a distinct verified replacement PR')
        replaced_by, replacement_raw = _lifecycle_request(root, repo, args.replacement_pr)
        merge = replacement_raw.get('merge_commit_sha')
        merged_at = replaced_by['merged_at']
        if (replaced_by['state'] != 'closed' or not isinstance(merged_at, str)
                or not isinstance(merge, str) or not SHA_RE.fullmatch(merge)
                or replaced_by['base'] != target['base']
                or not isinstance(replacement_raw.get('body'), str)
                or f"| {target['url']} | {target['head']} |" not in
                   [line.strip() for line in replacement_raw['body'].splitlines()]):
            raise ValueError('Replacement must be merged and retain this exact original PR and head')
        merged_time = datetime.fromisoformat(merged_at.replace('Z', '+00:00'))
        if merged_time.tzinfo is None or merged_time > datetime.now(UTC):
            raise ValueError('Replacement merge evidence has an invalid time')
        current_base = hosted_remote_sha(root, repo, target['base'])
        if not current_base:
            raise ValueError('Replacement ancestry is unavailable')
        ancestry = run_command(['gh', 'api', '--hostname', 'github.com',
                                f'repos/{repo}/compare/{merge}...{current_base}'], root, check=False)
        if ancestry.returncode:
            raise ValueError('Replacement merge is not verified in the selected remote base')
        comparison = json.loads(ancestry.stdout)
        if (not isinstance(comparison, dict)
                or comparison.get('base_commit', {}).get('sha') != merge
                or comparison.get('merge_base_commit', {}).get('sha') != merge
                or comparison.get('status') not in {'ahead', 'identical'}
                or type(comparison.get('behind_by')) is not int or comparison['behind_by'] != 0):
            raise ValueError('Replacement merge lacks authenticated remote ancestry')
        replacement = {**replaced_by, 'merge_commit': merge,
                       'body_sha256': hashlib.sha256(replacement_raw['body'].encode()).hexdigest(),
                       'verified_base': current_base}
    elif args.replacement_pr is not None:
        raise ValueError('Replacement evidence applies only to supersession close')
    return {'repository': repo, 'host': 'github.com', 'target': target,
            'replacement': replacement, 'local': _lifecycle_local_context(root, args),
            'observed': {'ci': 'not accepted by lifecycle evidence',
                         'reviews': 'not accepted by lifecycle evidence',
                         'mergeable': raw.get('mergeable')}}


def _lifecycle_transition(operation: str, target: dict[str, Any]) -> dict[str, Any]:
    if target['merged_at'] is not None:
        raise ValueError('Merged PRs cannot receive this lifecycle transition')
    after = {'state': target['state'], 'draft': target['draft']}
    if operation == 'close' and target['state'] == 'open':
        after['state'] = 'closed'
    elif operation == 'reopen' and target['state'] == 'closed':
        after['state'] = 'open'
    elif operation == 'ready' and target['state'] == 'open' and target['draft']:
        after['draft'] = False
    else:
        raise ValueError('Lifecycle operation does not match the target pre-state')
    return after


def _lifecycle_execute(root: Path, args: argparse.Namespace, identity: Any) -> dict[str, Any]:
    """A metadata transition proves no CI, review, thread or merge clearance."""
    if (args.expected_head or args.expected_thread_id or args.review_waiver_file
            or args.export_review_clearance or args.expected_base
            or sum(bool(value) for value in (args.write_receipt, args.check_receipt, args.apply_lifecycle)) != 1):
        raise ValueError('Lifecycle mode admits one explicit operation without unrelated authority')
    path = args.receipt or root / '.tmp/pr-lifecycle.v1.json'
    _scope.require_policy_repository_path(root, path, output=args.write_receipt)
    snapshot = _lifecycle_snapshot(root, args)
    if args.write_receipt:
        transition = _lifecycle_transition(args.lifecycle, snapshot['target'])
        result = {'schema_version': 'pr-lifecycle/v1', 'status': 'pass',
                  'operation': args.lifecycle, 'checked_at': datetime.now(UTC).isoformat(),
                  'acceptance_claims_proven': False, 'snapshot': snapshot, 'after': transition}
        _scope.require_policy_repository_identity(root, identity)
        _scope.write_policy_repository_receipt(root, path,
            (json.dumps(result, sort_keys=True) + '\n').encode(), identity)
        return result
    raw = _scope.policy_repository_read(root, path)
    if len(raw) > 64 * 1024:
        raise ValueError('Lifecycle receipt exceeds the bounded format')
    receipt = json.loads(raw)
    if (not isinstance(receipt, dict)
            or set(receipt) != {'schema_version', 'status', 'operation', 'checked_at',
                                'acceptance_claims_proven', 'snapshot', 'after'}
            or receipt['schema_version'] != 'pr-lifecycle/v1' or receipt['status'] != 'pass'
            or receipt['operation'] != args.lifecycle or receipt['acceptance_claims_proven'] is not False):
        raise ValueError('Lifecycle receipt is malformed or belongs to another operation')
    checked = datetime.fromisoformat(receipt['checked_at'])
    if checked.tzinfo is None:
        raise ValueError('Lifecycle receipt has no timezone')

    def require_fresh() -> None:
        age = (datetime.now(UTC) - checked).total_seconds()
        if not 0 <= age <= 300:
            raise ValueError('Lifecycle receipt is stale')

    require_fresh()
    recorded = receipt['snapshot']
    expected_after = _lifecycle_transition(args.lifecycle, recorded['target'])
    if receipt['after'] != expected_after:
        raise ValueError('Lifecycle receipt changed its expected transition')
    # CI and review observations are never clearance and may change independently.
    def comparable(item):
        return {key: value for key, value in item.items() if key != 'observed'}
    if comparable(snapshot) != comparable(recorded):
        raise ValueError('Lifecycle target, replacement, scope or local identity changed')
    _scope.require_policy_repository_identity(root, identity)
    if args.check_receipt:
        return receipt
    # Re-read immediately before the one fixed mutation. No arbitrary REST body,
    # comment, branch deletion, merge or review-submission option is admitted.
    final = _lifecycle_snapshot(root, args)
    if comparable(final) != comparable(recorded):
        raise ValueError('Lifecycle evidence changed before mutation')
    if args.lifecycle == 'ready':
        query = ('mutation($id:ID!){markPullRequestReadyForReview(input:{pullRequestId:$id})'
                 '{pullRequest{id isDraft state headRefOid}}}')
        command = ['gh', 'api', 'graphql', '--hostname', 'github.com', '-f', 'query=' + query,
                   '-f', 'id=' + recorded['target']['node_id']]
    else:
        command = ['gh', 'api', '--hostname', 'github.com', '--method', 'PATCH',
                   f'repos/{args.expected_repo}/pulls/{args.expected_pr}',
                   '-f', 'state=' + expected_after['state']]
    require_fresh()
    response = run_command(command, root, check=False)
    after, _raw = _lifecycle_request(root, args.expected_repo, args.expected_pr)
    expected = {**recorded['target'], **expected_after}
    if response.returncode or after != expected:
        raise ValueError('Lifecycle transition may have occurred; exact readback did not verify it')
    _scope.require_policy_repository_identity(root, identity)
    return {'schema_version': 'pr-lifecycle/v1', 'status': 'pass', 'operation': args.lifecycle,
            'target': after, 'acceptance_claims_proven': False, 'transition_verified': True}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--phase", choices=PHASES)
    modes.add_argument("--lifecycle", choices=('close', 'ready', 'reopen'))
    parser.add_argument('--lifecycle-head')
    parser.add_argument('--replacement-pr', type=int)
    parser.add_argument('--apply-lifecycle', action='store_true')
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--base")
    parser.add_argument("--remote", choices=(TRUSTED_REMOTE,), default=TRUSTED_REMOTE)
    parser.add_argument("--scope-file", type=Path)
    parser.add_argument("--review-waiver-file", type=Path)
    parser.add_argument("--export-review-clearance", action="store_true",
                        help="Print an incomplete disposition template without writing a receipt")
    parser.add_argument("--write-receipt", action="store_true")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--check-receipt", action="store_true")
    parser.add_argument("--max-receipt-age", type=int, default=900)
    parser.add_argument("--expected-repo")
    parser.add_argument("--expected-pr", type=int)
    parser.add_argument("--expected-thread-id")
    parser.add_argument("--expected-base")
    parser.add_argument("--expected-head")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repository = args.repo_root or Path.cwd()
    try:
        repository = resolve_root(repository)
        _scope.require_policy_repository_path(repository, repository)
        repository_identity = _scope.policy_repository_identity(repository)
        for candidate in (args.scope_file, args.review_waiver_file, args.receipt):
            if candidate is not None:
                _scope.require_policy_repository_path(repository, candidate)
    except (OSError, ValueError, CommandFailure):
        print(json.dumps({"schema_version": SCHEMA_VERSION, "status": "blocked",
                          "phase": args.phase, "error": "Readiness resource admission failed"}))
        return 2
    try:
        root = repository
        if getattr(args, 'lifecycle', None):
            try:
                result = _lifecycle_execute(root, args, repository_identity)
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                print(json.dumps({'schema_version': 'pr-lifecycle/v1', 'status': 'blocked',
                    'acceptance_claims_proven': False,
                    'error': 'Lifecycle evidence is invalid, stale or changed; a transition may have occurred if apply was requested'}))
                return 2
            print(json.dumps(result, sort_keys=True))
            return 0
        if (getattr(args, 'apply_lifecycle', False) or getattr(args, 'lifecycle_head', None)
                or getattr(args, 'replacement_pr', None) is not None):
            raise ValueError('Lifecycle arguments require their explicit mode')
        if args.export_review_clearance:
            if args.phase != "update" or args.write_receipt or args.check_receipt or args.review_waiver_file:
                raise CommandFailure(["--export-review-clearance"], "template export is update-only and cannot consume evidence or write a receipt")
            _branch, head, _base, _git_dir, _common = current_worktree(root)
            pr, error = gh_pr(root, for_export=True)
            if error or not isinstance(pr, dict) or not SHA_RE.fullmatch(head) or pr.get("headRefOid") != head or pr.get("state") != "OPEN":
                raise CommandFailure(["gh", "pr", "view"], error or "template requires an open PR with matching local and hosted head")
            if type(pr.get("number")) is not int or pr["number"] < 1:
                raise CommandFailure(["gh", "pr", "view"], "invalid PR number")
            slug, error = repository_slug(root)
            if error or not slug:
                raise CommandFailure(["gh", "repo", "view"], error or "repository unavailable")
            hostname, error = review_repository_host(pr, slug)
            if error or not hostname:
                raise CommandFailure(["gh", "pr", "view"], error or "repository host unavailable")
            sources, error = collect_clearance_sources(root, pr["number"], slug, hostname)
            if error or not sources:
                raise CommandFailure(["gh", "api"], error or "review source inventory is required")
            final_sources, error = collect_clearance_sources(root, pr["number"], slug, hostname)
            if error or final_sources != sources:
                raise CommandFailure(["gh", "api"], error or "review source inventories changed during collection; retry export")
            final_pr, error = gh_pr(root, for_export=True)
            if error or not isinstance(final_pr, dict) or any(type(final_pr.get(key)) is not type(pr[key]) or final_pr[key] != pr[key] for key in ("number", "headRefOid", "state", "url")):
                raise CommandFailure(["gh", "pr", "view"], error or "PR identity or head changed during source collection")
            try:
                final_reviews = clearance_sources(final_pr["reviews"], [], [])
            except ValueError as exc:
                raise CommandFailure(["gh", "api"], str(exc)) from exc
            if final_reviews != [source for source in final_sources if source["kind"] == "review"]:
                raise CommandFailure(["gh", "api"], "formal review inventory changed during final PR recheck; retry export")
            final_slug, error = repository_slug(root)
            if error or final_slug != slug:
                raise CommandFailure(["gh", "repo", "view"], error or "repository identity changed during source collection")
            if git(root, "rev-parse", "HEAD") != head:
                raise CommandFailure(["git", "rev-parse", "HEAD"], "local head changed during source collection")
            print(json.dumps(add_service_identity({
                "schema_version": "pr-review-clearance/v1", "repository": slug,
                "repository_host": hostname,
                "pr_number": pr["number"], "head_sha": head,
                "sources": [{"url": source["url"], "sha256": source["sha256"],
                             "disposition": "pending", "reason": "", "evidence_urls": []}
                            for source in sources],
            }), indent=2, sort_keys=True))
            return 0
        if args.check_receipt:
            _branch, _head, _base, git_dir, _common = current_worktree(root)
            path = args.receipt or default_receipt(root, git_dir)
            payload, error = validate_receipt(path, args)
            _scope.require_policy_repository_identity(repository, repository_identity)
            if error:
                result = add_service_identity({"schema_version": SCHEMA_VERSION, "status": "blocked", "phase": args.phase, "error": error, "receipt": str(path)})
                print(json.dumps(result, indent=2, sort_keys=True))
                return 2
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        result = build_result(args)
        _scope.require_policy_repository_identity(repository, repository_identity)
        if args.write_receipt:
            schema_error = validate_receipt_schema(result)
            if schema_error:
                raise CommandFailure(['--write-receipt'],
                    'Readiness result cannot be persisted as a receipt: ' + schema_error)
            path = args.receipt or Path(result["receipt"]["path"])
            _scope.require_policy_repository_path(repository, path, output=True)
            _scope.require_policy_repository_identity(repository, repository_identity)
            _scope.write_policy_repository_receipt(
                repository, path, (json.dumps(result, indent=2, sort_keys=True) + "\n").encode("utf-8"),
                repository_identity)
            result["receipt"]["path"] = str(path)
        result = add_service_identity(result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] == "pass" else 1 if result["status"] == "fail" else 2
    except CommandFailure as exc:
        result = add_service_identity({"schema_version": SCHEMA_VERSION, "status": "blocked", "phase": args.phase, "error": exc.reason, "command": " ".join(exc.command)})
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2
    except (OSError, ValueError):
        print(json.dumps({"schema_version": SCHEMA_VERSION, "status": "blocked",
                          "phase": args.phase, "error": "Readiness resource changed or is unavailable"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
