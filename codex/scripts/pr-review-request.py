"""Post a fixed inspection-only request after consuming its phase-bound receipt."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import UTC, datetime, timedelta
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


sys.path.insert(0, str(Path(__file__).resolve().parent))
SPEC = importlib.util.spec_from_file_location(
    "inspection_readiness", Path(__file__).with_name("pr-readiness.py")
)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def request_body(
    reviewer: str,
    head: str,
    clarify: bool,
    source: str | None = None,
    retry_source: str | None = None,
) -> str:
    """Use the collector's canonical request identity for every request mode."""
    return GATE.inspection_request_body(reviewer, head, clarify, source, retry_source)


def historical_full_request(body: str) -> str:
    """Retain the exact prior request identity for chronology and dedup only."""
    formal = "Publish the normal automatic review completion or a formal review on this exact head; a conversational reply alone cannot provide CodeRabbit clearance. "
    return body.replace(formal, "", 1)


def clarification_sources(entries: list[dict], source: str, head: str) -> list[dict]:
    """Select authenticated exact-source, current-head CodeRabbit evidence."""
    return [
        entry
        for entry in entries
        if isinstance(entry.get("html_url"), str)
        and entry["html_url"].casefold() == source.casefold()
        and (GATE._review_login(entry) == "coderabbitai")
        and isinstance(entry.get("user"), dict)
        and (entry["user"].get("type") == "Bot")
        and (type(entry["user"].get("id")) is int)
        and (entry["user"]["id"] > 0)
        and (head in GATE._review_body(entry))
    ]


def retry_sources(entries: list[dict], source: str, head: str) -> list[dict]:
    """Admit a delayed retry only for an authenticated failed current-head review."""
    admitted = []
    for entry in clarification_sources(entries, source, head):
        body = GATE._review_body(entry)
        legacy_limit = "Action not completed" in body and "Review rate limited." in body
        included_limit = (
            all(
                marker in body
                for marker in (
                    "<!-- This is an auto-generated comment: rate limited by coderabbit.ai -->",
                    "> ## Review limit reached",
                    "The included review limit has been reached and this organization has disabled usage-based review continuation.",
                    "<!-- end of auto-generated comment: rate limited by coderabbit.ai -->",
                )
            )
            and re.search(
                "\\*\\*Next included review available in [0-9]+ minutes?\\.\\*\\*", body
            )
            is not None
        )
        if not (legacy_limit or included_limit):
            continue
        try:
            response_time = datetime.fromisoformat(
                entry.get("updated_at", entry["created_at"])
            )
        except (KeyError, AttributeError, TypeError, ValueError):
            continue
        if response_time.tzinfo is None or datetime.now(
            UTC
        ) - response_time < timedelta(hours=1):
            continue
        admitted.append(entry)
    return admitted


def authenticated_actor(root: Path) -> dict:
    """Share request actor validation with the readiness collector."""
    return GATE.authenticated_review_actor(root)


def unedited_actor_requests(
    entries: list[dict], actor: dict, prefix: str, bodies: set[str]
) -> list[dict]:
    """Select exact-body, exact-PR requests by this actor, preserving input order."""
    return [
        entry
        for entry in entries
        if isinstance(entry.get("body"), str)
        and entry["body"] in bodies
        and isinstance(entry.get("html_url"), str)
        and entry["html_url"].casefold().startswith(prefix.casefold())
        and entry["html_url"][len(prefix) :].isdigit()
        and isinstance(entry.get("user"), dict)
        and (type(entry["user"].get("id")) is int)
        and (entry["user"]["id"] == actor["id"])
        and (entry["user"].get("login") == actor["login"])
        and (GATE._codex_event_time(entry.get("created_at")) is not None)
        and (
            GATE._codex_event_time(entry.get("updated_at"))
            == GATE._codex_event_time(entry["created_at"])
        )
    ]


def reinspection_source(
    root: Path,
    args: argparse.Namespace,
    head: str,
    entries: list[dict],
    receipt_base: tuple[str, str],
) -> dict:
    """Admit one new inspection for a later, still-outstanding CodeRabbit concern."""
    source = args.reinspect_source
    pr_url = f"https://github.com/{args.repo}/pull/{args.pr}"
    prefix = f"{pr_url}#issuecomment-"
    inline_prefix = f"{pr_url}#discussion_r"
    is_issue = isinstance(source, str) and source.casefold().startswith(
        prefix.casefold()
    )
    is_inline = isinstance(source, str) and source.casefold().startswith(
        inline_prefix.casefold()
    )
    suffix = (
        source[len(inline_prefix if is_inline else prefix) :]
        if isinstance(source, str)
        else ""
    )
    if (
        args.reviewer != "coderabbitai"
        or args.clarify
        or args.clarify_source
        or getattr(args, "retry_unavailable_source", None)
        or not (is_issue or is_inline)
        or re.fullmatch(r"[1-9][0-9]*", suffix) is None
    ):
        raise ValueError(
            "reinspection requires an exact-PR CodeRabbit concern source, without clarification"
        )
    inline, error = GATE.review_comments(root, args.pr)
    if error:
        raise ValueError(error)
    if is_inline:
        admitted = [
            item
            for item in inline
            if isinstance(item.get("html_url"), str)
            and item["html_url"].casefold() == source.casefold()
        ]
    else:
        admitted = clarification_sources(entries, source, head)
    if len(admitted) != 1:
        raise ValueError(
            "reinspection requires one authenticated current-head CodeRabbit concern"
        )
    entry = admitted[0]
    if is_inline:
        user = entry.get("user")
        api_url = f"https://api.github.com/repos/{args.repo}/pulls/{args.pr}"
        if (
            type(entry.get("id")) is not int
            or entry["id"] != int(suffix)
            or entry.get("in_reply_to_id") is not None
            or GATE._review_sha(entry) != head
            or entry.get("original_commit_id") != head
            or not isinstance(entry.get("pull_request_url"), str)
            or entry["pull_request_url"].casefold() != api_url.casefold()
            or not isinstance(user, dict)
            or GATE._review_login(entry) != "coderabbitai"
            or user.get("type") != "Bot"
            or type(user.get("id")) is not int
            or user["id"] <= 0
            or not isinstance(entry.get("body"), str)
            or not entry["body"].strip()
        ):
            raise ValueError(
                "reinspection requires one authenticated current-head CodeRabbit concern"
            )
    created = GATE._codex_event_time(entry.get("created_at"))
    updated = GATE._codex_event_time(entry.get("updated_at"))
    if not created or not updated or updated < created:
        raise ValueError(
            "reinspection concern timestamps are unavailable or inconsistent"
        )
    if "CodeRabbit" not in GATE.outstanding_bot_concerns(
        [], [entry] if is_inline else [], [] if is_inline else [entry], head
    ):
        raise ValueError("reinspection source is not a review concern")
    actor = authenticated_actor(root)
    original_body = request_body("coderabbitai", head, False)
    historical = historical_full_request(original_body)
    original_bodies = {
        original_body,
        historical,
        original_body.replace("\n\n", " ", 1),
        historical.replace("\n\n", " ", 1),
    }
    prior = [
        item
        for item in unedited_actor_requests(entries, actor, prefix, original_bodies)
        if GATE._codex_event_time(item["created_at"]) < created
    ]
    if not prior:
        raise ValueError(
            "reinspection concern must follow an authenticated current-head inspection request"
        )
    same_source = GATE.reinspection_request_body(head, entry["html_url"])
    historical_same_source = historical_full_request(same_source)
    reusable = {
        same_source,
        historical_same_source,
        historical_same_source.replace("\n\n", " ", 1),
    }
    for item in entries:
        body = item.get("body")
        if (
            not isinstance(body, str)
            or re.match(
                r"\s*@coderabbitai\s+full\s+review(?:\s|$)", body, re.IGNORECASE
            )
            is None
        ):
            continue
        if body in reusable:
            if not unedited_actor_requests([item], actor, prefix, reusable):
                raise ValueError(
                    "existing source-bound request is not authenticated and unedited"
                )
            if GATE._codex_event_time(item["created_at"]) <= updated:
                raise ValueError(
                    "existing source-bound request does not follow the current finding"
                )
            continue  # The execution path will reuse this exact request.
        if not is_inline:
            continue
        # An older inline finding must not be used as a new source after any
        # subsequent full-review request, including a differently sourced retry.
        url = item.get("html_url")
        started = GATE._codex_event_time(item.get("created_at"))
        changed = GATE._codex_event_time(item.get("updated_at"))
        if (
            not isinstance(url, str)
            or not url.casefold().startswith(prefix.casefold())
            or re.fullmatch(r"[1-9][0-9]*", url[len(prefix) :]) is None
            or not started
            or not changed
            or changed < started
            or changed >= created
        ):
            raise ValueError(
                "inline reinspection concern must be later than every full-review request"
            )
    pr, error = GATE.gh_pr(root, number=args.pr, for_export=True)
    if (
        error
        or not pr
        or pr.get("state") != "OPEN"
        or (pr.get("headRefOid") != head)
        or (str(pr.get("url", "")).casefold() != prefix.split("#")[0].casefold())
    ):
        raise ValueError(error or "reinspection PR identity or head changed")
    if (pr.get("baseRefName"), pr.get("baseRefOid")) != receipt_base:
        raise ValueError(
            "reinspection PR base no longer matches the inspection receipt"
        )
    lane = GATE.reviews_lane(root, pr, head)
    if "CodeRabbit" not in lane.get("details", {}).get("outstanding_bot_concerns", []):
        raise ValueError(
            "CodeRabbit no longer has a verified outstanding review concern"
        )
    if not isinstance(pr.get("reviews"), list):
        raise ValueError("reinspection formal review inventory is unavailable")  # noqa: TRY004 -- blocked hosted evidence
    has_summary = any(
        GATE._review_login(item) == "coderabbitai"
        and "<!-- This is an auto-generated comment: summarize by coderabbit.ai -->"
        in GATE._review_body(item)
        for item in entries
    )
    statuses = GATE._coderabbit_statuses(root, args.repo, head) if has_summary else None
    if has_summary and statuses is None:
        raise ValueError("CodeRabbit completion status inventory unavailable")
    completion, error = GATE.coderabbit_completion_review(
        root, pr, head, inline, entries
    )
    if error:
        raise ValueError(error)
    verified, error = GATE._codex_completion_snapshot(
        root, pr, inline, entries, None, args.repo
    )
    if not verified:
        raise ValueError(error or "reinspection review inventory unavailable")
    if has_summary and GATE._coderabbit_statuses(root, args.repo, head) != statuses:
        raise ValueError(
            "CodeRabbit completion status inventory changed or became unavailable"
        )
    if completion is not None and completion.get("html_url") == entry.get("html_url"):
        raise ValueError("the selected reinspection concern has already been cleared")
    # Retain only this concern and all potential clearances. Another later
    # concern must not reopen a selected source that was already cleared.
    clear_reviews = [
        item for item in pr["reviews"] if GATE._bot_review_is_acceptable(item, head)
    ]
    clear_inline = [
        item
        for item in inline
        if (is_inline and item == entry)
        or GATE._bot_review_is_acceptable({**item, "state": "COMMENTED"}, head)
    ]
    selected_comments = [
        item
        for item in entries
        if (is_issue and item == entry)
        or GATE._bot_review_is_acceptable({**item, "state": "COMMENTED"}, head)
    ]
    if completion is not None:
        selected_comments.append(completion)
    if "CodeRabbit" not in GATE.outstanding_bot_concerns(
        clear_reviews, clear_inline, selected_comments, head
    ):
        raise ValueError("the selected reinspection concern has already been cleared")
    return entry


def quota_retry_body(head: str, source: str) -> str:
    """Use the same fixed source-bound body for admission and deduplication."""
    return (
        request_body("codex", head, False)
        + f" Retry follows the authenticated service failure at {source}. This source permits only one deduplicated retry, not review clearance."
    )


def pending_codex_summary(body: str, head: str) -> bool:
    """Recognize a minimal neutral pending marker; unknown content stays blocking."""
    match = GATE.re.fullmatch(
        "<!-- codex-pull-request-review-summary -->\\s+<!-- codex-review-state:v1 (.*?) -->\\s+## Codex Review Summary\\s*",
        body,
        GATE.re.DOTALL,
    )
    if not match:
        return False
    try:
        state = json.loads(match[1], object_pairs_hook=GATE._unique_provider_object)
    except (ValueError, TypeError):
        return False
    if not isinstance(state, dict) or set(state) != {"code_review", "security_review"}:
        return False
    pending = {
        "commit_sha": head,
        "has_any_findings": None,
        "has_unresolved_findings": None,
        "status": "running",
    }
    unstarted = {key: None for key in pending}
    return state["code_review"] == pending and state["security_review"] in (
        unstarted,
        pending,
    )


def failed_codex_activity(
    entry: dict,
    failure: dict,
    args: argparse.Namespace,
    head: str,
    request_time: datetime,
) -> bool:
    """Bind the fixed failed activity envelope to a later quota failure, not clearance."""
    prefix = f"https://github.com/{args.repo}/pull/{args.pr}#issuecomment-"
    url = entry.get("html_url")
    if (
        entry.get("user") != failure.get("user")
        or not isinstance(url, str)
        or (not url.casefold().startswith(prefix.casefold()))
        or (not url[len(prefix) :].isdigit())
    ):
        return False
    body = GATE._review_body(entry)
    match = re.fullmatch(
        '<!-- codex-pull-request-review-summary -->\\s+<!-- codex-review-state:v1 ([^\\n]+) -->\\s+<!-- codex-security-review:v1 ([^\\n]+) -->\\s+## Codex Review Summary\\s+This comment shows the latest Codex review activity on this pull request\\.\\s+\\| Review \\| Status \\| Commit \\| Review trigger \\|\\s+\\| --- \\| --- \\| --- \\| --- \\|\\s+\\| 📝 \\*\\*Code Review\\*\\* \\| ⚠️ \\*\\*Failed\\*\\* <relative-time datetime="([^"]+)">\\3</relative-time> \\| `([0-9a-f]{7,40}|[0-9a-f]{64})` \\| Manual request \\|\\s+\\| 🔒 \\*\\*Security Review\\*\\* \\| ✅ \\*\\*Completed\\*\\* <relative-time datetime="([^"]+)">\\5</relative-time> \\| `([0-9a-f]{7,40}|[0-9a-f]{64})` \\| (?:Draft marked ready|Manual request|Automatic|PR opened|New commits) \\|\\s+<details>\\s*<summary>ℹ️ About Codex in GitHub</summary>\\s*<br/>\\s*\\[Your team has set up Codex to review pull requests in this repo\\]\\(https://chatgpt\\.com/codex/cloud/settings/general\\)\\. Reviews are triggered when you\\s+- Open a pull request for review\\s+- Mark a draft as ready\\s+- Comment "@codex review" or "@codex security review"\\.\\s+Codex reacts with 👀 while any review is running, comments if it has suggestions, and reacts with 👍 once all reviews finish with no findings\\.\\s*</details>\\s*',
        body,
    )
    if not match:
        return False
    try:
        state = json.loads(match[1], object_pairs_hook=GATE._unique_provider_object)
        security = json.loads(match[2], object_pairs_hook=GATE._unique_provider_object)
    except (ValueError, TypeError):
        return False
    if not isinstance(state, dict) or set(state) != {"code_review", "security_review"}:
        return False
    if any(
        not isinstance(item, dict)
        or any(
            type(item.get(key)) is not bool
            for key in ("has_any_findings", "has_unresolved_findings")
        )
        for item in state.values()
    ):
        return False
    if state["code_review"] != {
        "commit_sha": head,
        "has_any_findings": True,
        "has_unresolved_findings": True,
        "status": "failed",
    }:
        return False
    if not isinstance(security, dict) or set(security) != {
        "blockingSeverityThreshold",
        "headSha",
        "mergeGateEnabled",
        "pullRequestNumber",
        "repository",
        "status",
    }:
        return False
    security_head = security["headSha"]
    if (
        not isinstance(security_head, str)
        or not GATE.SHA_RE.fullmatch(security_head)
        or security["blockingSeverityThreshold"] not in ("P0", "P1", "P2", "P3")
        or (security["mergeGateEnabled"] is not False)
        or (security["status"] != "completed")
        or (type(security["pullRequestNumber"]) is not int)
        or (security["pullRequestNumber"] != args.pr)
        or (not isinstance(security["repository"], str))
        or (security["repository"].casefold() != args.repo.casefold())
        or (
            state["security_review"]
            != {
                "commit_sha": security_head,
                "has_any_findings": False,
                "has_unresolved_findings": False,
                "status": "completed",
            }
        )
        or (not head.startswith(match[4]))
        or (not security_head.startswith(match[6]))
    ):
        return False
    completed = GATE._codex_event_time(match[3])
    security_time = GATE._codex_event_time(match[5])
    updated = GATE._codex_event_time(entry.get("updated_at"))
    failed_at = GATE._codex_event_time(failure.get("created_at"))
    return bool(
        completed
        and security_time
        and updated
        and failed_at
        and (security_time <= completed)
        and (request_time <= completed < failed_at)
        and (updated < failed_at)
        and (completed <= updated or completed.replace(microsecond=0) == updated)
    )


def quota_retry_source(
    root: Path, args: argparse.Namespace, head: str, entries: list[dict]
) -> dict:
    """Admit one Codex retry after authenticated failure and this head's request."""
    source = args.retry_source
    prefix = f"https://github.com/{args.repo}/pull/{args.pr}#issuecomment-"
    if (
        args.reviewer != "codex"
        or args.clarify
        or args.clarify_source is not None
        or (getattr(args, "retry_unavailable_source", None) is not None)
        or (getattr(args, "reinspect_source", None) is not None)
        or (not isinstance(source, str))
        or (not source.casefold().startswith(prefix.casefold()))
        or (not source[len(prefix) :].isdigit())
    ):
        raise ValueError(
            "quota retry requires an exact-PR Codex source without other request modes"
        )
    matches = [
        entry
        for entry in entries
        if isinstance(entry.get("html_url"), str)
        and entry["html_url"].casefold() == source.casefold()
    ]
    if len(matches) != 1:
        raise ValueError(
            "quota retry requires one authenticated Codex service-failure source"
        )
    failure = matches[0]
    user = failure.get("user")
    created = GATE._codex_event_time(failure.get("created_at"))
    updated = GATE._codex_event_time(failure.get("updated_at"))
    if (
        not isinstance(user, dict)
        or user.get("login") != "chatgpt-codex-connector[bot]"
        or user.get("type") != "Bot"
        or (type(user.get("id")) is not int)
        or (user["id"] <= 0)
        or (not created)
        or (not updated)
        or (updated < created)
        or (
            not GATE._bot_response_is_only_unavailability(
                GATE._review_body(failure), login="chatgpt-codex-connector"
            )
        )
    ):
        raise ValueError(
            "quota retry requires an authenticated standalone Codex service failure"
        )
    actor = authenticated_actor(root)
    prior = [
        entry
        for entry in unedited_actor_requests(
            entries, actor, prefix, {request_body("codex", head, False)}
        )
        if (
            GATE._codex_event_time(entry["created_at"]),
            int(entry["html_url"][len(prefix) :]),
        )
        < (created, int(failure["html_url"][len(prefix) :]))
    ]
    if not prior:
        raise ValueError(
            "quota source must follow an authenticated exact current-head request"
        )
    request_time, request_id = max(
        (
            GATE._codex_event_time(entry["created_at"]),
            int(entry["html_url"][len(prefix) :]),
        )
        for entry in prior
    )
    existing_retries = [
        entry
        for entry in unedited_actor_requests(
            entries, actor, prefix, {quota_retry_body(head, failure["html_url"])}
        )
        if (
            GATE._codex_event_time(entry["created_at"]),
            int(entry["html_url"][len(prefix) :]),
        )
        > (created, int(failure["html_url"][len(prefix) :]))
    ]
    for entry in entries:
        if entry == failure:
            continue
        body = GATE._review_body(entry)
        is_request = (
            GATE.re.search("@codex\\s+review\\b", body, GATE.re.IGNORECASE) is not None
        )
        is_response = GATE._review_login(entry) == "chatgpt-codex-connector"
        if not is_request and (not is_response):
            continue
        event_created = GATE._codex_event_time(entry.get("created_at"))
        event_time = (
            GATE._codex_event_time(entry.get("updated_at"))
            if is_response
            else event_created
        )
        if not event_created or not event_time or event_time < event_created:
            raise ValueError("Codex request or response chronology is unavailable")
        if event_time < request_time or entry in prior:
            continue
        if is_response and failed_codex_activity(
            entry, failure, args, head, request_time
        ):
            continue
        if (
            is_response
            and (event_time < created or existing_retries)
            and pending_codex_summary(body, head)
        ):
            continue
        url = entry.get("html_url")
        ordered_url = (
            isinstance(url, str)
            and url.casefold().startswith(prefix.casefold())
            and url[len(prefix) :].isdigit()
        )
        if (
            event_time == event_created == request_time
            and ordered_url
            and (int(url[len(prefix) :]) < request_id)
        ):
            continue
        if entry in existing_retries:
            continue
        if (
            event_time <= created
            or is_request
            or (
                not GATE._bot_response_is_only_unavailability(
                    body, login="chatgpt-codex-connector"
                )
            )
        ):
            raise ValueError(
                "quota failure is separated from its request by another Codex event"
            )
    pr, error = GATE.gh_pr(root, number=args.pr, for_export=True)
    if (
        error
        or not pr
        or pr.get("state") != "OPEN"
        or (pr.get("headRefOid") != head)
        or (str(pr.get("url", "")).casefold() != prefix.split("#")[0].casefold())
    ):
        raise ValueError(error or "quota retry PR identity or head changed")
    if not isinstance(pr.get("reviews"), list):
        raise ValueError("quota retry formal review inventory is unavailable")  # noqa: TRY004 - MIG-HELPER-1: preserve the domain-invalid-evidence API; instructions/migration-scope.md#helper-boundary-decisions
    for review in pr["reviews"]:
        if GATE._review_login(review) != "chatgpt-codex-connector":
            continue
        reviewed_head = GATE._review_sha(review)
        if not isinstance(reviewed_head, str) or not GATE.SHA_RE.fullmatch(
            reviewed_head
        ):
            raise ValueError("quota retry formal review commit identity is unavailable")
        if reviewed_head == head:
            raise ValueError(
                "quota retry cannot repeat an existing current-head Codex review"
            )
    return failure


def execute(args: argparse.Namespace) -> dict:
    root = GATE.resolve_root(args.repo_root)
    _branch, head, _base, git_dir, _common = GATE.current_worktree(root)
    receipt = args.receipt or GATE.default_receipt(root, git_dir)
    consumer = argparse.Namespace(
        phase="review_inspection",
        repo_root=root,
        base=getattr(args, "base", None),
        remote="origin",
        max_receipt_age=900,
        expected_repo=args.repo,
        expected_pr=args.pr,
        expected_thread_id=None,
        expected_base=None,
        expected_head=None,
    )
    payload, error = GATE.validate_receipt(receipt, consumer)
    if error:
        raise ValueError(error)
    if payload.get("authority") != GATE.review_inspection_authority():
        raise ValueError("receipt does not admit inspection-only requests")
    source = args.clarify_source
    retry_source = getattr(args, "retry_unavailable_source", None)
    if retry_source and args.clarify_source:
        raise ValueError("retry and clarification sources are mutually exclusive")
    source_snapshot = None
    reinspect = getattr(args, "reinspect_source", None)
    concern = None
    receipt_base = None
    codex_retry_source = getattr(args, "retry_source", None)
    failure = None
    if codex_retry_source is not None:
        entries, error = GATE.issue_comments(root, args.pr)
        if error:
            raise ValueError(error)
        failure = quota_retry_source(root, args, head, entries)
    if reinspect:
        repo = payload.get("repo")
        if (
            not isinstance(repo, dict)
            or not isinstance(repo.get("base_branch"), str)
            or not repo["base_branch"]
            or not isinstance(repo.get("remote_base_sha"), str)
            or not GATE.SHA_RE.fullmatch(repo["remote_base_sha"])
        ):
            raise ValueError("inspection receipt base is malformed")
        receipt_base = (repo["base_branch"], repo["remote_base_sha"])
        entries, error = GATE.issue_comments(root, args.pr)
        if error:
            raise ValueError(error)
        concern = reinspection_source(root, args, head, entries, receipt_base)
    if args.clarify or retry_source:
        source = source if args.clarify else retry_source
        prefix = f"https://github.com/{args.repo}/pull/{args.pr}#issuecomment-"
        if (
            not isinstance(source, str)
            or not source.casefold().startswith(prefix.casefold())
            or (not source[len(prefix) :].isdigit())
        ):
            raise ValueError("review source must belong to the exact repository and PR")
        entries, error = GATE.issue_comments(root, args.pr)
        if error:
            raise ValueError(error)
        admitted = (clarification_sources if args.clarify else retry_sources)(
            entries, source, head
        )
        if args.reviewer != "coderabbitai" or len(admitted) != 1:
            raise ValueError(
                "retry requires one authenticated, elapsed CodeRabbit rate-limit source"
                if retry_source
                else "clarification requires one authenticated CodeRabbit source mentioning the current full head"
            )
        source = admitted[0]["html_url"]
        source_snapshot = json.dumps(admitted[0], sort_keys=True)
    elif args.clarify_source:
        raise ValueError("clarification source requires --clarify")
    body = request_body(
        args.reviewer,
        head,
        args.clarify,
        source if args.clarify else None,
        source if retry_source else None,
    )
    if concern is not None:
        body = GATE.reinspection_request_body(head, concern["html_url"])
    if failure is not None:
        body = quota_retry_body(head, failure["html_url"])
    if args.dry_run:
        if GATE.git(root, "rev-parse", "HEAD") != head:
            raise ValueError("HEAD changed before dry-run completion")
        return {"status": "pass", "dry_run": True, "head": head, "body": body}
    entries, error = GATE.issue_comments(root, args.pr)
    if error:
        raise ValueError(error)
    if failure is not None and quota_retry_source(root, args, head, entries) != failure:
        raise ValueError("quota retry source changed before mutation")
    if concern is not None:
        if receipt_base is None:
            raise ValueError("inspection receipt base is unavailable")
        refreshed_concern = reinspection_source(root, args, head, entries, receipt_base)
        if refreshed_concern != concern:
            raise ValueError("reinspection concern changed before mutation")
    if args.clarify or retry_source:
        refreshed = (clarification_sources if args.clarify else retry_sources)(
            entries, source, head
        )
        if (
            len(refreshed) != 1
            or json.dumps(refreshed[0], sort_keys=True) != source_snapshot
        ):
            raise ValueError(
                "clarification source changed before mutation"
                if args.clarify
                else "retry source changed before mutation"
            )
    compatible_bodies = {body}
    if args.reviewer == "coderabbitai" and (not args.clarify):
        historical = historical_full_request(body)
        compatible_bodies.update({historical, historical.replace("\n\n", " ", 1)})
    prefix = f"https://github.com/{args.repo}/pull/{args.pr}#issuecomment-"
    for entry in entries:
        url = entry.get("html_url")
        if (
            isinstance(entry.get("body"), str)
            and entry["body"] in compatible_bodies
            and isinstance(url, str)
            and url.casefold().startswith(prefix.casefold())
            and url[len(prefix) :].isdigit()
        ):
            actor = authenticated_actor(root)
            owner = entry.get("user")
            if (
                not isinstance(owner, dict)
                or type(owner.get("id")) is not int
                or owner["id"] != actor["id"]
                or (owner.get("login") != actor["login"])
                or (GATE._codex_event_time(entry.get("created_at")) is None)
                or (
                    GATE._codex_event_time(entry.get("updated_at"))
                    != GATE._codex_event_time(entry.get("created_at"))
                )
            ):
                continue
            pr, pr_error = GATE.gh_pr(root, number=args.pr, for_export=True)
            if (
                pr_error
                or not pr
                or pr.get("state") != "OPEN"
                or pr.get("headRefOid") != head
                or not isinstance(pr.get("url"), str)
                or pr["url"].casefold() != prefix.split("#")[0].casefold()
                or (
                    receipt_base is not None
                    and (pr.get("baseRefName"), pr.get("baseRefOid")) != receipt_base
                )
                or GATE.git(root, "rev-parse", "HEAD") != head
            ):
                raise ValueError(
                    pr_error or "reused request current-head verification failed"
                )
            return {
                "status": "pass",
                "head": head,
                "url": url,
                "reused": True,
                "acceptance_claims_proven": False,
            }
    # Execution approval remains necessary for this normal remote mutation.
    if concern is not None:
        refreshed_receipt, error = GATE.validate_receipt(receipt, consumer)
        if error or refreshed_receipt != payload:
            raise ValueError(
                error or "inspection receipt changed before request mutation"
            )
        latest_entries, error = GATE.issue_comments(root, args.pr)
        if error:
            raise ValueError(error)
        if (
            reinspection_source(root, args, head, latest_entries, receipt_base)
            != concern
        ):
            raise ValueError("reinspection concern changed before mutation")
        if any(
            isinstance(item.get("body"), str)
            and item["body"] in compatible_bodies
            and isinstance(item.get("html_url"), str)
            and item["html_url"].casefold().startswith(prefix.casefold())
            and item["html_url"][len(prefix) :].isdigit()
            for item in latest_entries
        ):
            raise ValueError(
                "inspection request appeared during final recheck; retry to verify and reuse it"
            )
    if GATE.git(root, "rev-parse", "HEAD") != head:
        raise ValueError("HEAD changed before request mutation")
    result = GATE.run_command(
        ["gh", "pr", "comment", str(args.pr), "--repo", args.repo, "--body", body], root
    )
    url = result.stdout.strip()
    entries, error = GATE.issue_comments(root, args.pr)
    pr, pr_error = GATE.gh_pr(root, number=args.pr, for_export=True)
    if (
        error
        or pr_error
        or not pr
        or pr.get("state") != "OPEN"
        or pr.get("headRefOid") != head
        or (
            receipt_base is not None
            and (pr.get("baseRefName"), pr.get("baseRefOid")) != receipt_base
        )
        or GATE.git(root, "rev-parse", "HEAD") != head
        or not any(
            entry.get("html_url") == url and entry.get("body") == body
            for entry in entries
        )
    ):
        raise ValueError(
            error
            or pr_error
            or "request readback or current-head verification failed; request may have been posted"
        )
    return {
        "status": "pass",
        "head": head,
        "url": url,
        "acceptance_claims_proven": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument(
        "--base", help="Selected target branch, matching the inspection receipt"
    )
    parser.add_argument("--reviewer", choices=("codex", "coderabbitai"), required=True)
    parser.add_argument("--clarify", action="store_true")
    parser.add_argument(
        "--clarify-source",
        help="Current-head authenticated CodeRabbit issue-comment URL",
    )
    parser.add_argument(
        "--retry-unavailable-source",
        help="Authenticated current-head CodeRabbit rate-limit reply URL after one hour",
    )
    parser.add_argument(
        "--reinspect-source",
        help="Later outstanding CodeRabbit issue or inline review comment requiring a fresh inspection",
    )
    parser.add_argument(
        "--retry-source",
        help="Authenticated Codex service-failure URL after this head's exact request; one deduplicated retry",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = _fixture_args(parser.parse_args())
    try:
        result = execute(args)
    except (ValueError, GATE.CommandFailure) as exc:
        print(json.dumps({"schema_version": 1, "status": "blocked", "error": str(exc)}))
        return 2
    print(json.dumps({"schema_version": 1, **result}, indent=2))
    return 0


if __name__ == "__main__":
    _fixture_scope().admit_file(__file__)
    raise SystemExit(main())
