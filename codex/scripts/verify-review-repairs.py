"""Protected CI evidence producer. Never executes candidate code or grants receipts."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

from pr_repair_ci import BRANCH, REPOSITORY
from pr_repair_endorsement import MARKER, parse_endorsement


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


SPEC = importlib.util.spec_from_file_location(
    "readiness", Path(__file__).with_name("pr-readiness.py")
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("trusted readiness module is unavailable")
READINESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(READINESS)


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    try:
        revision = READINESS.git(root, "rev-parse", "HEAD")
        if (
            os.environ.get("CIRCLE_BRANCH") != BRANCH
            or os.environ.get("CIRCLE_SHA1") != revision
        ):
            raise ValueError("run from the protected verifier branch in CircleCI")
        repository, error = READINESS.repository_slug(root)
        if error or repository != REPOSITORY:
            raise ValueError(error or "verifier repository mismatch")
        result = READINESS.run_command(
            [
                "gh",
                "api",
                f"repos/{REPOSITORY}/pulls?state=open&per_page=100",
                "--paginate",
                "--slurp",
            ],
            root,
            timeout=30,
        )
        pages = json.loads(result.stdout)
        if (
            not isinstance(pages, list)
            or not pages
            or any(not isinstance(page, list) for page in pages)
        ):
            raise ValueError("invalid open PR inventory")
        numbers = [entry["number"] for page in pages for entry in page]
        if (
            len(numbers) > 50
            or len(set(numbers)) != len(numbers)
            or any(type(n) is not int or n < 1 for n in numbers)
        ):
            raise ValueError(
                "invalid or oversized PR inventory; inspect the queue manually"
            )
        output = root / ".tmp" / "repair-evidence"
        if (root / ".tmp").is_symlink() or output.is_symlink():
            raise ValueError("artifact directory must not be a symlink")
        _fixture_resource(output).mkdir(parents=True, exist_ok=True)
        for number in numbers:
            pr, error = READINESS.gh_pr(root, for_export=True, number=number)
            if error or not pr:
                raise ValueError(error or "PR unavailable")
            host, error = READINESS.review_repository_host(pr, REPOSITORY)
            if error:
                raise ValueError(error)
            collections = []
            for path in (
                f"pulls/{number}/reviews",
                f"pulls/{number}/comments",
                f"issues/{number}/comments",
            ):
                entries, error = READINESS.review_inventory_collection(
                    root, f"repos/{REPOSITORY}/{path}", host
                )
                if error:
                    raise ValueError(error)
                collections.append(entries)
            refs = {pr["headRefOid"], pr["baseRefOid"]}
            for review in collections[0]:
                reviewed_sha = READINESS._review_sha(review)
                if reviewed_sha is not None:
                    refs.add(reviewed_sha)
            invalid_endorsement = False
            for entries in collections:
                for entry in entries:
                    body = entry.get("body") or ""
                    if (
                        body.startswith(MARKER)
                        and READINESS._review_login(entry) in READINESS.BOT_REVIEWERS
                        and (
                            READINESS._review_login(entry)
                            != READINESS._review_login({"user": pr.get("author")})
                        )
                    ):
                        try:
                            refs.add(parse_endorsement(body).reviewed_commit)
                        except ValueError:
                            invalid_endorsement = True
            if any(
                not isinstance(ref, str) or not READINESS.SHA_RE.fullmatch(ref)
                for ref in refs
            ):
                raise ValueError("invalid source commit identity")
            if invalid_endorsement:
                evidence = {
                    "status": "blocked",
                    "evidence": "invalid endorsement in this PR",
                    "details": {},
                }
            else:
                READINESS.run_command(
                    [
                        "git",
                        "fetch",
                        "--no-tags",
                        "--no-recurse-submodules",
                        "origin",
                        *sorted(refs),
                    ],
                    root,
                    timeout=60,
                )
                evidence = READINESS.repair_endorsement_lane(
                    root,
                    pr,
                    pr["headRefOid"],
                    *collections,
                    require_protected_run=False,
                )
            report = {
                "schema_version": "pr-protected-repair/v1",
                "repository": REPOSITORY,
                "pr_number": number,
                "head_sha": pr["headRefOid"],
                "verifier_revision": revision,
                "status": evidence["status"],
                "inventory_digest": evidence.get("details", {}).get(
                    "inventory_digest", ""
                ),
                "evidence": evidence,
                "grants_merge_authority": False,
            }
            with _fixture_resource(output / f"pr-{number}.json").open(
                "x", encoding="utf-8"
            ) as handle:
                json.dump(report, handle, indent=2, sort_keys=True)
        print(
            json.dumps(
                {
                    "service": "protected-repair-verifier",
                    "status": "pass",
                    "reports": len(numbers),
                    "grants_merge_authority": False,
                }
            )
        )
        return 0
    except (ValueError, OSError, KeyError, TypeError, READINESS.CommandFailure) as exc:
        print(
            json.dumps(
                {
                    "service": "protected-repair-verifier",
                    "status": "blocked",
                    "error": str(exc).splitlines()[0],
                }
            )
        )
        return 2


if __name__ == "__main__":
    _fixture_scope().admit_file(__file__)
    raise SystemExit(main())
