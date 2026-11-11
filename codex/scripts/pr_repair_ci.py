"""Read authenticated CircleCI provenance; local JSON is never CI approval."""
from __future__ import annotations

import base64
import json
import os
import re
from collections.abc import Callable
from typing import Any, NoReturn
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import yaml

REPOSITORY = "jscraik/configs"
BRANCH = "codex/repair-verifier"
PROJECT = "eeb0216d-b44e-4d44-aada-2ef5a4bdeb6b"
JOB = "verify-review-repairs"
UUID_PATTERN = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> NoReturn:
        raise ValueError("artifact redirects are not accepted")


def protected_report(**arguments: Any) -> dict[str, str]:
    """Convert malformed or unavailable provider data to a closed evidence gap."""
    try:
        return _protected_report(**arguments)
    except (AttributeError, KeyError, TypeError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError("invalid protected CI provider evidence") from exc


def _protected_report(*, repository: str, number: int, head: str,
                      inventory_digest: str, command: Callable[[list[str]], str]) -> dict[str, str]:
    """Verify provider identities, protected source, executed commands and output."""
    if repository != REPOSITORY:
        raise ValueError("protected repair verifier is not configured for this repository")

    def read(*args):
        return json.loads(command(list(args)))

    rules = read("gh", "api", f"repos/{REPOSITORY}/rulesets/23077968")
    if rules.get("enforcement") != "active" or rules.get("bypass_actors") != []:
        raise ValueError("verifier source protections are not active without bypasses")
    if rules.get("conditions", {}).get("ref_name") != {"include": [f"refs/heads/{BRANCH}"], "exclude": []}:
        raise ValueError("verifier ruleset targets changed")
    kinds = {rule["type"]: rule for rule in rules.get("rules", [])}
    if not {"pull_request", "deletion", "non_fast_forward", "required_signatures"} <= kinds.keys():
        raise ValueError("verifier source protection is incomplete")
    parameters = kinds["pull_request"].get("parameters", {})
    count = parameters.get("required_approving_review_count")
    if type(count) is not int or count < 1:
        raise ValueError("verifier source requires independent approval")
    if not any(parameters.get(key) is True for key in (
        "dismiss_stale_reviews_on_push", "require_last_push_approval"
    )):
        raise ValueError("verifier source requires approval freshness after every push")
    ref = read("gh", "api", f"repos/{REPOSITORY}/git/ref/heads/{BRANCH}")
    revision = ref.get("object", {}).get("sha", "")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("protected verifier revision is unavailable")
    run = read("circleci", "run", "get", "--project", f"gh/{REPOSITORY}",
               "--branch", BRANCH, "--json", "--no-interactive")
    if (run.get("branch") != BRANCH or run.get("tag") or
        run.get("repository_url") != f"https://github.com/{REPOSITORY}" or
        run.get("commit", {}).get("url") != f"https://github.com/{REPOSITORY}/commit/{revision}"):
        raise ValueError("CI run is not bound to the protected verifier revision")
    jobs = [job for workflow in run.get("workflows", [])
            if workflow.get("name") == "repair-verification"
            for job in workflow.get("jobs", []) if job.get("name") == JOB]
    if len(jobs) != 1 or jobs[0].get("outcome") != "succeeded":
        raise ValueError("protected repair job has not succeeded")
    job_id = jobs[0].get("id", "")
    if not isinstance(job_id, str) or not re.fullmatch(UUID_PATTERN, job_id):
        raise ValueError("invalid provider job identifier")
    run_id = run.get("id", "")
    if not isinstance(run_id, str) or not re.fullmatch(UUID_PATTERN, run_id):
        raise ValueError("invalid provider run identifier")
    job = read("circleci", "job", "get", job_id, "--json")
    if job.get("project_id") != PROJECT or job.get("pipeline_id") != run.get("id") or job.get("outcome") != "succeeded":
        raise ValueError("job provenance mismatch")
    content = read("gh", "api", f"repos/{REPOSITORY}/contents/.circleci/config.yml?ref={revision}")
    source = base64.b64decode(content["content"]).decode()
    token = os.environ.get("CIRCLECI_CLI_TOKEN") or os.environ.get("CIRCLE_TOKEN") or os.environ.get("CIRCLECI_TOKEN")
    if not token:
        raise ValueError("existing CircleCI API credential is required to verify configuration provenance")
    request = Request(f"https://circleci.com/api/v2/pipeline/{run_id}/config", headers={"Circle-Token": token})
    with build_opener(NoRedirect()).open(request, timeout=15) as response:
        raw_config = response.read(2097153)
    if len(raw_config) > 2097152:
        raise ValueError("oversized provider configuration")
    provider_config = json.loads(raw_config)
    if provider_config.get("source") != source or provider_config.get("setup-config"):
        raise ValueError("provider configuration differs from the protected source")
    configuration = yaml.safe_load(source)
    expected = [step["run"]["command"].strip() for step in configuration["jobs"][JOB]["steps"]
                if isinstance(step, dict) and "run" in step]
    steps = [step for execution in job.get("executions", []) for step in execution.get("steps", [])]
    actual = [step.get("command", "").removeprefix("#!/bin/bash -eo pipefail\n").strip()
              for step in steps if step.get("type") == "run"]
    if not expected or actual != expected:
        raise ValueError("executed commands differ from protected verifier configuration")
    if any(step.get("type") not in {"run", "spinup_environment", "print_env", "checkout", "artifacts"} for step in steps):
        raise ValueError("unverified job step type")
    artifacts = read("circleci", "job", "artifact", job_id, "--json")
    matches = [item for item in artifacts if item.get("path") == f"repair-evidence/pr-{number}.json"]
    if len(matches) != 1:
        raise ValueError("current PR repair artifact is missing or ambiguous")
    url = matches[0]["url"]
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not (parsed.hostname or "").endswith(".circle-artifacts.com")
        or parsed.username or parsed.password or parsed.port not in {None, 443}):
        raise ValueError("artifact is outside the provider's HTTPS origin")
    with build_opener(NoRedirect()).open(url, timeout=15) as response:
        raw = response.read(1048577)
    if len(raw) > 1048576:
        raise ValueError("oversized repair artifact")
    report = json.loads(raw)
    expected_report = {"schema_version": "pr-protected-repair/v1", "repository": repository,
                       "pr_number": number, "head_sha": head, "inventory_digest": inventory_digest,
                       "verifier_revision": revision, "status": "pass"}
    if any(type(report.get(key)) is not type(value) or report[key] != value for key, value in expected_report.items()):
        raise ValueError("CI evidence does not match the current PR and source inventory")
    return {"job_id": job_id, "run_id": run["id"], "verifier_revision": revision, "artifact_url": url}
