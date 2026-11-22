"""Close one merged-PR evidence thread without asserting retrospective readiness."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from datetime import UTC, datetime
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
    "post_merge_gate", Path(__file__).with_name("pr-readiness.py")
)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)
SCHEMA = "post-merge-thread/v1"
WORKFLOW_SHA256 = "db23311dc79e9346b07108f5f7d0311e113a80945ebe457967fa0f3ee488724e"
COMMAND_STEPS = {
    "Quality and schema checks": "quality",
    "Full tests (two isolated workers and slow-test report)": "tests",
    "Build source and wheel": "build",
    "Installed public API and CLI proof": "installed",
    "Diff hygiene": "diff",
}
THREAD_QUERY = "query($id:ID!) { node(id:$id) { ... on PullRequestReviewThread {\n id isResolved isOutdated pullRequest { url number headRefOid }\n comments(first:100) { pageInfo { hasNextPage } nodes {\n id body url author { login __typename } originalCommit { oid }\n } } } } }"
REPLY_QUERY = "mutation($threadId:ID!,$body:String!){addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$threadId,body:$body}){comment{id}}}"
RESOLVE_QUERY = "mutation($threadId:ID!){resolveReviewThread(input:{threadId:$threadId}){thread{id}}}"


def read_json(root: Path, command: list[str]) -> dict:
    """Reject failed transport, GraphQL errors and non-object responses."""
    value = json.loads(GATE.run_command(command, root).stdout)
    if not isinstance(value, dict) or value.get("errors"):
        raise ValueError("invalid or failed provider response")
    return value


def git(root: Path, *args: str) -> str:
    """Use the existing bounded Git transport."""
    return GATE.run_command(["git", *args], root).stdout.strip()


def check_identity(root: Path, args: argparse.Namespace, pr: dict) -> dict:
    """Require an accepted exact squash tree, independent of deleted branches."""
    expected_url = f"https://github.com/{args.repo}/pull/{args.pr}"
    record = pr.get("mergeCommit")
    head, base = (pr.get("headRefOid"), pr.get("baseRefOid"))
    merge = record.get("oid") if isinstance(record, dict) else None
    if (
        pr.get("url") != expected_url
        or pr.get("number") != args.pr
        or pr.get("state") != "MERGED"
        or (pr.get("baseRefName") != args.base)
        or any(
            not isinstance(sha, str) or not GATE.SHA_RE.fullmatch(sha)
            for sha in (head, base, merge)
        )
    ):
        raise ValueError("merged PR identity is invalid")
    slug, error = GATE.repository_slug(root)
    if error or slug != args.repo or GATE.dirty_lane(root)["status"] != "pass":
        raise ValueError("repository identity or clean accepted checkout is unproved")
    if git(root, "rev-parse", "HEAD") != merge:
        raise ValueError("checkout must equal the accepted merge commit")
    remote = git(root, "ls-remote", "origin", f"refs/heads/{args.base}").split()
    if len(remote) != 2 or remote != [merge, f"refs/heads/{args.base}"]:
        raise ValueError("selected accepted remote base must equal the merge")
    if git(root, "rev-list", "--parents", "-n", "1", merge).split() != [merge, base]:
        raise ValueError(
            "only a single-parent merge with the immutable original base is supported"
        )
    tree = git(root, "rev-parse", f"{head}^{{tree}}")
    if tree != git(root, "rev-parse", f"{merge}^{{tree}}"):
        raise ValueError("complete reviewed and accepted trees differ")
    return {"reviewed_head": head, "original_base": base, "merge": merge, "tree": tree}


def read_thread(
    root: Path, args: argparse.Namespace, head: str, *, resolved: bool = False
) -> dict:
    """Bind the complete bounded thread to this PR and reviewed commit."""
    value = read_json(
        root,
        [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={THREAD_QUERY}",
            "-f",
            f"id={args.thread}",
        ],
    )
    thread = value.get("data", {}).get("node")
    if not isinstance(thread, dict):
        raise TypeError("thread is unavailable")
    comments = thread.get("comments", {})
    nodes = comments.get("nodes")
    if (
        thread.get("id") != args.thread
        or thread.get("isResolved") is not resolved
        or thread.get("isOutdated") is not False
        or (
            thread.get("pullRequest")
            != {
                "url": f"https://github.com/{args.repo}/pull/{args.pr}",
                "number": args.pr,
                "headRefOid": head,
            }
        )
        or (comments.get("pageInfo", {}).get("hasNextPage") is not False)
        or (not isinstance(nodes, list))
        or (not nodes)
        or (not all(isinstance(item, dict) for item in nodes))
    ):
        raise ValueError("thread identity, completeness or state is unproved")
    source = nodes[0]
    if (
        source.get("author") != {"login": "coderabbitai", "__typename": "Bot"}
        or source.get("originalCommit") != {"oid": head}
        or (not isinstance(source.get("body"), str))
        or (not source["body"])
        or (source.get("id") != args.source_comment)
        or (hashlib.sha256(source["body"].encode()).hexdigest() != args.source_sha256)
    ):
        raise ValueError("original current-head CodeRabbit comment is unproved")
    return thread


def validate_run(root: Path, args: argparse.Namespace, run: dict, head: str) -> None:
    """Bind validation to the accepted workflow and unambiguous PR association."""
    if type(run.get("workflow_id")) is not int or run["workflow_id"] <= 0:
        raise ValueError("workflow identity is missing")
    workflow = read_json(
        root, ["gh", "api", f"repos/{args.repo}/actions/workflows/{run['workflow_id']}"]
    )
    path = ".github/workflows/validate.yml"
    if (
        run.get("path") != path
        or workflow.get("id") != run["workflow_id"]
        or workflow.get("path") != path
    ):
        raise ValueError("only the accepted validation workflow is supported")
    git(root, "cat-file", "-e", f"HEAD:{path}")
    linked = run.get("pull_requests")
    if not isinstance(linked, list):
        raise TypeError("run PR association is unavailable")
    if linked:
        if (
            len(linked) != 1
            or not isinstance(linked[0], dict)
            or linked[0].get("number") != args.pr
        ):
            raise ValueError("run belongs to another or ambiguous PR")
        return
    pages = json.loads(
        GATE.run_command(
            [
                "gh",
                "api",
                f"repos/{args.repo}/commits/{head}/pulls",
                "--paginate",
                "--slurp",
            ],
            root,
        ).stdout
    )
    if not isinstance(pages, list) or not all(isinstance(page, list) for page in pages):
        raise ValueError("commit PR inventory is malformed")
    entries = [item for page in pages for item in page]
    expected_url = f"https://github.com/{args.repo}/pull/{args.pr}"
    if (
        len(entries) != 1
        or not isinstance(entries[0], dict)
        or entries[0].get("number") != args.pr
        or (entries[0].get("html_url") != expected_url)
    ):
        raise ValueError(
            "deleted-branch run requires one authenticated commit-associated PR"
        )


def command_evidence(
    root: Path, args: argparse.Namespace, head: str, job_url: str
) -> dict:
    """Bind exact commands to one supported immutable workflow and executed steps."""
    source = GATE.run_command(
        ["git", "show", f"{head}:.github/workflows/validate.yml"], root
    ).stdout
    digest = hashlib.sha256(source.encode()).hexdigest()
    if digest != WORKFLOW_SHA256:
        raise ValueError(
            "validation command mapping requires the supported immutable workflow"
        )
    job_id = int(job_url.rsplit("/", 1)[1])
    job = read_json(root, ["gh", "api", f"repos/{args.repo}/actions/jobs/{job_id}"])
    if (
        job.get("id") != job_id
        or job.get("run_id") != args.run
        or job.get("head_sha") != head
        or (job.get("html_url") != job_url)
        or (job.get("status") != "completed")
        or (job.get("conclusion") != "success")
        or (not isinstance(job.get("steps"), list))
    ):
        raise ValueError("successful immutable validation job is unproved")
    steps = []
    for name, phase in COMMAND_STEPS.items():
        matches = [
            step
            for step in job["steps"]
            if isinstance(step, dict) and step.get("name") == name
        ]
        if (
            len(matches) != 1
            or matches[0].get("status") != "completed"
            or matches[0].get("conclusion") != "success"
            or (type(matches[0].get("number")) is not int)
        ):
            raise ValueError(
                "required validation command was missing, ambiguous, skipped or unsuccessful"
            )
        steps.append(
            {
                "number": matches[0]["number"],
                "name": name,
                "command": f"bash scripts/validate-repository.sh {phase}",
                "outcome": "pass",
            }
        )
    return {
        "workflow_sha256": digest,
        "job_id": job_id,
        "job_url": job_url,
        "steps": steps,
    }


def collect(root: Path, args: argparse.Namespace, *, resolved: bool = False) -> dict:
    """Collect fresh merge, CI and thread evidence; grant no readiness claim."""
    fields = "number,url,state,headRefOid,baseRefName,baseRefOid,mergeCommit,statusCheckRollup"
    pr = read_json(
        root, ["gh", "pr", "view", str(args.pr), "--repo", args.repo, "--json", fields]
    )
    identity = check_identity(root, args, pr)
    head = identity["reviewed_head"]
    # The exact validate run and immutable workflow are authenticated below;
    # this preliminary gate rejects any visible failed or incomplete sibling.
    if GATE.observed_checks_lane(pr, head)["status"] != "pass":
        raise ValueError("all reported current-head checks must pass")
    run = read_json(root, ["gh", "api", f"repos/{args.repo}/actions/runs/{args.run}"])
    run_url = f"https://github.com/{args.repo}/actions/runs/{args.run}"
    if (
        type(run.get("id")) is not int
        or run.get("id") != args.run
        or run.get("head_sha") != head
        or (run.get("event") != "pull_request")
        or (run.get("status") != "completed")
        or (run.get("conclusion") != "success")
        or (run.get("html_url") != run_url)
        or (run.get("repository", {}).get("full_name") != args.repo)
    ):
        raise ValueError("successful immutable reviewed-head CI run is unproved")
    validate_run(root, args, run, head)
    linked = [
        item
        for item in pr["statusCheckRollup"]
        if item.get("__typename") == "CheckRun"
        and item.get("name") == "validate"
        and (item.get("conclusion") == "SUCCESS")
        and re.fullmatch(re.escape(run_url) + "/job/[0-9]+", item.get("detailsUrl", ""))
    ]
    if len(linked) != 1:
        raise ValueError("validation check is not uniquely bound to the successful run")
    commands = command_evidence(root, args, head, linked[0]["detailsUrl"])
    thread = read_thread(root, args, head, resolved=resolved)
    actor = read_json(root, ["gh", "api", "user"])
    if (
        type(actor.get("id")) is not int
        or actor["id"] <= 0
        or (not isinstance(actor.get("login"), str))
    ):
        raise ValueError("authenticated reply actor is unavailable")
    body = (
        f"Post-merge evidence closeout for {head}: validation run {run_url} completed successfully. The accepted merge {identity['merge']} has the identical complete Git tree. This records validation evidence for this thread only; it does not establish retrospective review or merge readiness.\n\n"
        + "\n".join(
            f"Command: `{step['command']}` -> pass" for step in commands["steps"]
        )
    )
    reply_count = 0
    for item in thread["comments"]["nodes"][1:]:
        if (
            item.get("body") != body
            or item.get("author", {}).get("login") != actor["login"]
            or (not isinstance(item.get("id"), str))
            or (not item["id"])
        ):
            raise ValueError(
                "later thread comments are not covered by the evidence-only disposition"
            )
        reply_count += 1
    if reply_count > 1:
        raise ValueError("multiple matching evidence replies; thread left unresolved")
    return {
        "schema_version": SCHEMA,
        "repo": args.repo,
        "pr": args.pr,
        "base": args.base,
        **identity,
        "run": args.run,
        "run_updated_at": run.get("updated_at"),
        "command_evidence": commands,
        "thread": thread,
        "actor": {"id": actor["id"], "login": actor["login"]},
        "reply": body,
        "reply_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "acceptance_claims_proven": False,
        "allowed_mutations": ["thread_reply", "thread_resolve"],
    }


def execute(root: Path, args: argparse.Namespace, snapshot: dict) -> dict:
    """Recheck the complete snapshot, post the bound reply and verify resolution."""
    receipt = json.loads(_fixture_resource(args.receipt).read_text())
    if not isinstance(receipt, dict) or not isinstance(receipt.get("checked_at"), str):
        raise TypeError("receipt envelope is malformed")
    created = datetime.fromisoformat(receipt["checked_at"])
    age = (datetime.now(UTC) - created).total_seconds()
    if not 0 <= age <= 600 or receipt.get("evidence") != snapshot:
        raise ValueError("receipt is stale or does not match fresh evidence")
    if collect(root, args) != snapshot:
        raise ValueError("evidence changed before mutation")
    nodes = snapshot["thread"]["comments"]["nodes"]

    def owns_reply(item: dict) -> bool:
        return (
            isinstance(item.get("id"), str)
            and bool(item["id"])
            and (item.get("body") == snapshot["reply"])
            and (item.get("author", {}).get("login") == snapshot["actor"]["login"])
        )

    if not all(owns_reply(item) for item in nodes[1:]):
        raise ValueError("existing evidence reply identity is unproved")
    reply_count = sum(owns_reply(item) for item in nodes[1:])
    if reply_count > 1:
        raise ValueError("multiple matching evidence replies; thread left unresolved")
    outcome = "reply_verified" if reply_count == 1 else "no_mutation"
    try:
        if outcome == "no_mutation":
            outcome = "reply_requested_outcome_unknown"
            result = read_json(
                root,
                [
                    "gh",
                    "api",
                    "graphql",
                    "-f",
                    f"query={REPLY_QUERY}",
                    "-f",
                    f"threadId={args.thread}",
                    "-f",
                    f"body={snapshot['reply']}",
                ],
            )
            posted = (
                result.get("data", {})
                .get("addPullRequestReviewThreadReply", {})
                .get("comment", {})
                .get("id")
            )
            current = collect(root, args)
            expected = dict(snapshot)
            expected["thread"] = current["thread"]
            additions = current["thread"]["comments"]["nodes"][len(nodes) :]
            if (
                current != expected
                or current["thread"]["comments"]["nodes"][: len(nodes)] != nodes
                or sum(
                    owns_reply(item)
                    for item in current["thread"]["comments"]["nodes"][1:]
                )
                != 1
                or (not isinstance(posted, str))
                or (not posted)
                or (len(additions) != 1)
                or (not isinstance(additions[0].get("id"), str))
                or (not additions[0]["id"] == posted)
                or (not owns_reply(additions[0]))
            ):
                raise ValueError(
                    "reply readback or evidence changed; thread left unresolved"
                )
            outcome = "reply_verified"
        else:
            current = snapshot
        if collect(root, args) != current:
            raise ValueError("evidence changed before resolution")
        outcome = "resolution_requested_outcome_unknown"
        read_json(
            root,
            [
                "gh",
                "api",
                "graphql",
                "-f",
                f"query={RESOLVE_QUERY}",
                "-f",
                f"threadId={args.thread}",
            ],
        )
        final = collect(root, args, resolved=True)
        expected = json.loads(json.dumps(current))
        expected["thread"]["isResolved"] = True
        if final != expected:
            raise ValueError("evidence changed during resolution")
    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        OSError,
        GATE.CommandFailure,
    ) as exc:
        return {
            "status": "blocked",
            "thread": args.thread,
            "mutation_outcome": outcome,
            "error": str(exc),
            "acceptance_claims_proven": False,
        }
    return {
        "status": "pass",
        "thread": args.thread,
        "mutation_outcome": "resolution_verified",
        "acceptance_claims_proven": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--thread", required=True)
    parser.add_argument("--run", type=int, required=True)
    parser.add_argument("--source-comment", required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument(
        "--evidence-only",
        action="store_true",
        required=True,
        help="Operator independently adjudicated this exact source as a validation-evidence request only",
    )
    parser.add_argument("--base", default="main")
    parser.add_argument("--receipt", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--write-receipt", action="store_true")
    mode.add_argument("--execute", action="store_true")
    args = _fixture_args(parser.parse_args())
    try:
        if (
            not re.fullmatch("[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo)
            or not re.fullmatch("PRRT_[A-Za-z0-9_-]+", args.thread)
            or (not re.fullmatch("PRRC_[A-Za-z0-9_-]+", args.source_comment))
            or (not re.fullmatch("[0-9a-f]{64}", args.source_sha256))
            or (args.pr <= 0)
            or (args.run <= 0)
            or (args.base != "main")
        ):
            raise ValueError("invalid bounded reconciliation target")
        root = args.repo_root.resolve(strict=True)
        if args.receipt.resolve().is_relative_to(root):
            raise ValueError("receipt must remain outside the accepted checkout")
        snapshot = collect(root, args)
        if args.execute:
            result = execute(root, args, snapshot)
        else:
            if collect(root, args) != snapshot:
                raise ValueError("evidence changed during preflight")
            result = {
                "status": "pass",
                "evidence": snapshot,
                "checked_at": datetime.now(UTC).isoformat(),
            }
            if args.write_receipt:
                _fixture_scope().output(args.receipt).write_text(
                    json.dumps(result, indent=2) + "\n"
                )
        print(
            json.dumps(
                {
                    "schema_version": SCHEMA,
                    "service": "pr-post-merge-reconciliation",
                    "acceptance_claims_proven": False,
                    **result,
                },
                indent=2,
            )
        )
        return 0 if result["status"] == "pass" else 2
    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        OSError,
        GATE.CommandFailure,
    ) as exc:
        print(
            json.dumps(
                {
                    "schema_version": SCHEMA,
                    "service": "pr-post-merge-reconciliation",
                    "acceptance_claims_proven": False,
                    "status": "blocked",
                    "error": str(exc),
                }
            )
        )
        return 2


if __name__ == "__main__":
    _fixture_scope().admit_file(__file__)
    raise SystemExit(main())
