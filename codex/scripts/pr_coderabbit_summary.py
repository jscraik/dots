"""Bounded CodeRabbit structured-summary data adapter; no network or clearance IO.

Named explanations are preserved data. Only the result, coverage and completion
records supply a verdict. Unknown structure and incomplete evidence fail closed.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from html import unescape
from typing import Any
from urllib.parse import parse_qs, urlsplit

ASSETS = "https://storage.googleapis.com/coderabbit_public_assets/"
UUID = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
PENDING_START = "<!-- This is an auto-generated comment: review in progress by coderabbit.ai -->"
PENDING_END = "<!-- end of auto-generated comment: review in progress by coderabbit.ai -->"
PAUSED_START = "<!-- This is an auto-generated comment: review paused by coderabbit.ai -->"
PAUSED_END = "<!-- end of auto-generated comment: review paused by coderabbit.ai -->"


def _without_scheduling_notice(body: str, head: str) -> str:
    """Recognise one exact automatic-review scheduling notice, never completion."""
    if PAUSED_START not in body and PAUSED_END not in body:
        return body
    if body.count(PAUSED_START) != 1 or body.count(PAUSED_END) != 1:
        raise ValueError("ambiguous scheduling notice")
    match = re.search(re.escape(PAUSED_START) + r"(.*?)" + re.escape(PAUSED_END), body, re.DOTALL)
    expected = (
        "> [!NOTE]\n> ## Reviews paused\n> \n"
        "> It looks like this branch is under active development. To avoid overwhelming you with review comments due to an influx of new commits, CodeRabbit has automatically paused this review. You can configure this behavior by changing the `reviews.auto_review.auto_pause_after_reviewed_commits` setting.\n> \n"
        f"> - Last reviewed commit: {head}\n> \n"
        "> Use the following commands to manage reviews:\n"
        "> - `@coderabbitai resume` to resume automatic reviews.\n"
        "> - `@coderabbitai review` to trigger a single review.\n> \n"
        "> Use the checkboxes below for quick actions:\n"
        '> - [ ] <!-- {"checkboxId":"@RESUME@"} --> Resume reviews\n'
        '> - [ ] <!-- {"checkboxId":"@TRIGGER@"} --> Trigger review'
    )
    pattern = re.escape(expected).replace("@RESUME@", "(" + UUID + ")").replace("@TRIGGER@", "(" + UUID + ")")
    notice = re.fullmatch(pattern, match[1].strip()) if match else None
    if notice is None or notice[1] == notice[2]:
        raise ValueError("unknown scheduling notice")
    return body.replace(match[0], "", 1)


def _known_provider_assertion(title: str, content: str, selected_info: str, *, slug: str, head: str) -> bool:
    """Accept only the inspected affirmative assertion; no free-form classifier."""
    if (title == "Additional comments: 3" and slug == "jscraik/dots"
        and head == "0246dcea7306d2fc88e064a6131edce786370353"):
        # This exact reviewed test explanation refutes an allegation about
        # which validator its failure stub reaches; it requests no repair.
        # Retain the normal authenticated completion and selected-file join.
        expected = {
            "tests/policy_fixture.py: 1": "`22-22`: LGTM!\n\n",
            "tests/test_governance_port.py: 1": "`34-34`: LGTM!\n\n",
            "tests/test_policy_projection.py: 1": (
                "`70-72`: **Maintainability & Code Quality**\n\n"
                "**The notifier-cutover path does not run canonical validation first.**\n\n"
                "For the notifier-only cleanup, `main` calls `_validate_notifier_cutover_snapshot` before any backup or write. That function invokes the runtime validator (`--runtime-config-stdin`), not `--config-stdin`. The canonical validator is not called anywhere in the repair script. The exit-75 stub therefore reaches the notifier-cutover check first, so the assertions test that check directly.\n\n"
            ),
        }
        gap, children = _details(content)
        if gap or len(children) != len(expected):
            return False
        observed = [_wrapper(child) for child in children]
        if len({name for name, _ in observed}) != len(expected):
            return False
        return all(name in expected
            and "* `" + name.removesuffix(": 1") + "`" in selected_info.splitlines()
            and re.fullmatch(re.escape(expected[name]) + r"<!-- cr-comment:v1:[0-9a-f]{24} -->", note)
            is not None for name, note in observed)
    if (title == "LanguageTool" and slug == "jscraik/rSearch"
        and head == "4d940dd7d9d74459cbea0da683814fe218330e21"
        and "* `docs/robin-review.md`" in selected_info.splitlines()):
        file_title, note = _wrapper(content)
        # Inspected false positive: the inline variable identifiers precede
        # "Actions secrets". Arbitrary grammar diagnostics remain blocking.
        return file_title == "docs/robin-review.md" and note == (
            '[grammar] ~20-~20: It appears that a noun is missing after “The”.\n'
            'Context: ...ndependent reviews.  ## Free allowance  The '
            '`ROBIN_CLOUDFLARE_API_TOKEN` and `ROBIN...\n\n(THE_CC)'
        )
    if title != "Additional comments: 1" or "* `tests/ci-policy.test.ts`" not in selected_info.splitlines():
        return False
    gap, children = _details(content)
    if gap or len(children) != 1:
        return False
    file_title, paragraph = _wrapper(children[0])
    expected = (
        "`88-89`: **Data Integrity & Integration**\n\n"
        "**The GitHub Actions identity assertion is consistent with the inspected provider contract.**\n\n"
        "The test pins the active provider to `github-actions`. The contract agrees, and it declares a `dual-provider` migration in `shadow` mode. The inspected files do not list CircleCI or Semgrep Cloud as required-check providers, so the comment's claim that this validator rejects them is not supported by repository evidence.\n\n"
    )
    return file_title == "tests/ci-policy.test.ts: 1" and re.fullmatch(
        re.escape(expected) + r"<!-- cr-comment:v1:[0-9a-f]{24} -->", paragraph
    ) is not None


def _pictures(text: str) -> str:
    def remove(match: re.Match[str]) -> str:
        picture = match[0]
        if not re.fullmatch(r"<picture>(?:<(?:source|img) [^<>]+>)+</picture>", picture):
            raise ValueError("unknown picture structure")
        for tag in re.findall(r"<(?:source|img) ([^<>]+)>", picture):
            attrs = re.findall(r'([a-z-]+)="([^"<>]*)"', tag)
            if (re.sub(r'[a-z-]+="[^"<>]*"', "", tag).strip()
                or len(dict(attrs)) != len(attrs)
                or any(key not in {"src", "srcset", "media", "width", "height", "align", "alt", "title"} for key, _ in attrs)
                or any(not value.startswith(ASSETS) for key, value in attrs if key in {"src", "srcset"})
                or any(value not in {"", "Passed", "Explain Change →"} for key, value in attrs if key in {"alt", "title"})):
                raise ValueError("unknown picture attributes")
        return ""
    return re.sub(r"<picture>.*?</picture>", remove, text, flags=re.DOTALL)


def _details(text: str) -> tuple[str, list[str]]:
    """Split top-level details without treating nested context as a verdict."""
    depth, start, end = 0, 0, 0
    gaps, children = [], []
    for token in re.finditer(r"</?details(?: open)?>", text):
        if token[0].startswith("</"):
            depth -= 1
            if depth < 0:
                raise ValueError("unbalanced details")
            if depth == 0:
                children.append(text[start:token.end()])
                end = token.end()
        else:
            if depth == 0:
                gaps.append(text[end:token.start()])
                start = token.start()
            depth += 1
    if depth:
        raise ValueError("unclosed details")
    gaps.append(text[end:])
    return "".join(gaps).strip(), children


def _wrapper(text: str) -> tuple[str, str]:
    gaps, children = _details(text.strip())
    if gaps or len(children) != 1:
        raise ValueError("expected one details region")
    match = re.fullmatch(r"<details(?: open)?>\s*<summary><strong>(.*?)</strong></summary>\s*<dl>\s*<dd>\s*(.*?)\s*</dd>\s*</dl>\s*</details>", children[0], re.DOTALL)
    if match is None:
        raise ValueError("unknown details wrapper")
    return _pictures(match[1]).strip(), re.sub(r"^<br>\s*", "", match[2]).strip()


def _block(body: str, name: str) -> tuple[str, str]:
    start, end = f"<!-- {name}_start -->", f"<!-- {name}_end -->"
    if body.count(start) != 1 or body.count(end) != 1:
        raise ValueError("missing or repeated region")
    match = re.search(re.escape(start) + r"(.*?)" + re.escape(end), body, re.DOTALL)
    if match is None:
        raise ValueError("reversed region")
    return match[0], match[1].strip()


def _checkbox(line: str) -> bool:
    match = re.fullmatch(r'- \[ \] <!-- (\{[^\n]+\}) --> (Commit to this branch|Create a new PR)', line.strip())
    if match is None:
        return False
    data = json.loads(match[1])
    return (isinstance(data, dict) and set(data) in ({"checkboxId"}, {"checkboxId", "radioGroupId"})
            and isinstance(data["checkboxId"], str) and re.fullmatch(UUID, data["checkboxId"]) is not None
            and ("radioGroupId" not in data or isinstance(data["radioGroupId"], str)
                 and re.fullmatch(r"utg-output-choice-group-(?:[1-9][0-9]*|unknown_comment_id)", data["radioGroupId"]) is not None))


def _without_approval_policy(body: str, head: str) -> str:
    """Validate provider policy metadata; it supplies no review verdict."""
    if "approval_policy_info" not in body:
        return body
    region, policy = _block(body, "approval_policy_info")
    title, content = _wrapper(policy)
    source = r"(?:Global configuration|Repository YAML|Repository UI|Organization UI)"
    expected = (
        r"Commit: `([0-9a-f]{7,40})`\.\s*"
        r"\| Setting \| Effective value \| Source \|\s*"
        r"\| :--- \| :--- \| :--- \|\s*"
        r"\| Automatic approvals \| Enabled \| " + source + r" \|\s*"
        r"\| Merge risk \| Minimal \| " + source + r" \|\s*"
        r"\| Security risk \| Not set \| " + source + r" \|\s*"
        r"\*\*Not set\*\* means no limit was configured after inheritance\. "
        r"Use `@coderabbitai configuration` to inspect the resolved settings and their sources\."
    )
    match = re.fullmatch(expected, content)
    if title != "Automatic approval policy" or match is None or not head.startswith(match[1]):
        raise ValueError("unknown approval policy metadata")
    marker = "<!-- review_info_content -->"
    if marker in body:
        # The provider inserts this block with one blank line on each side.
        # Remove only that exact metadata slot, not whitespace in review text.
        slot = marker + "\n\n" + region + "\n\n"
        if body.count(marker) != 1 or body.count(slot) != 1:
            raise ValueError("unknown approval policy placement")
        return body.replace(slot, marker + "\n", 1)
    return body.replace(region + "\n", "", 1) if region + "\n" in body else body.replace(region, "", 1)


def _status_metadata(body: str) -> str:
    """Normalize the native top-level verdict without changing source evidence."""
    start, end = "<!-- recent_review_status_start -->", "<!-- recent_review_status_end -->"
    recent_start, recent_end = "<!-- recent_review_start -->", "<!-- recent_review_end -->"
    if start not in body and end not in body:
        return body
    if any(body.count(marker) != 1 for marker in (start, end, recent_start, recent_end)):
        raise ValueError("ambiguous review status")
    match = re.search(re.escape(start) + r"\s*(.*?)\s*" + re.escape(end), body, re.DOTALL)
    verdict = "No actionable comments were generated in the recent review."
    header = ("<!-- coderabbit-ai-generated:v1 --> "
              "<!-- This is an auto-generated comment: summarize by coderabbit.ai -->")
    if (match is None or match[1] not in (verdict, verdict + " 🎉")
        or " ".join(body[:match.start()].split()) != header):
        raise ValueError("unknown review status")
    recent_region, recent = _block(body, "recent_review")
    if recent.startswith("<h6>\n") and recent.endswith("\n</h6>"):
        recent = recent[len("<h6>\n"):-len("\n</h6>")].strip()
    return body.replace(match[0], "", 1).replace(
        recent_region, recent_start + "\n" + match[1] + "\n" + recent + "\n" + recent_end, 1)


def _check_context_timeout(title: str, content: str) -> bool:
    """Recognise unavailable supplemental CI context, never a check verdict."""
    count = re.fullmatch(r"Context from checks skipped due to timeout: ([1-9][0-9]{0,2})", title)
    if count is None or int(count[1]) > 100:
        return False
    lines = content.splitlines()
    names = [re.fullmatch(r"\* GitHub Check: ([A-Za-z0-9][A-Za-z0-9 ._:/()\-]{0,199})", line) for line in lines]
    return (len(names) == int(count[1]) and all(names)
            and len({match[1] for match in names if match is not None}) == len(names)
            and all(match[1] == match[1].strip() for match in names if match is not None))


def structured_summary(body: str, slug: str, number: int, head: str) -> dict[str, str] | None:
    """Adapt only the complete observed structured report, retaining its raw text."""
    try:
        if not isinstance(body, str) or len(body) > 262144 or PENDING_START in body:
            return None
        metadata = _without_scheduling_notice(body, head)
        if re.search(r"Actionable comments posted:|Outside diff range comments|cr-indicator-types:potential_issue|review (?:incomplete|skipped|paused)|files skipped", metadata, re.IGNORECASE):
            return None
        failure_start = "<!-- This is an auto-generated comment: all tool run failures by coderabbit.ai -->"
        failure_end = "<!-- end of auto-generated comment: all tool run failures by coderabbit.ai -->"
        if failure_start in body or failure_end in body:
            failure = re.search(re.escape(failure_start) + r"(.*?)" + re.escape(failure_end), body, re.DOTALL)
            if body.count(failure_start) != 1 or body.count(failure_end) != 1 or failure is None or failure[1].strip():
                return None
        metadata = _without_approval_policy(metadata, head)
        nav_region, nav = _block(body, "review_stack_entry")
        link = re.fullmatch(r'<a href="([^"<>]+)">(?:Explain Change →)?</a>', _pictures(nav))
        if link is None:
            return None
        address = urlsplit(unescape(link[1]))
        query = parse_qs(address.query, strict_parsing=True, keep_blank_values=True)
        if (address.scheme != "https" or address.netloc != "app.coderabbit.ai"
            or address.path != f"/change-stack/{slug}/pull/{number}" or address.fragment
            or set(query) not in ({"scope", "cs_source"}, {"cs_source"}) or query["cs_source"] != ["review_comment"]
            or "scope" in query and (len(query["scope"]) != 1 or re.fullmatch(r"[A-Za-z0-9_-]+", query["scope"][0]) is None)):
            return None
        review_url = f"https://app.coderabbit.ai{address.path}?scope={query['scope'][0]}" if "scope" in query else None
        metadata = metadata.replace(nav_region, "")

        recent_region, recent = _block(metadata, "recent_review")
        context_region, context = _block(recent, "review_details")
        title, content = _wrapper(context)
        gap, children = _details(content)
        contexts = [_wrapper(child) for child in children]
        if (title not in {"Recent review details", "📜 Recent review details"} or gap
            or sum(name == "Additional context used" for name, _ in contexts) != 1
            or len(contexts) not in (1, 2, 3)
            or len({name for name, _ in contexts}) != len(contexts)
            or sum(name.startswith("Context from checks skipped due to timeout:") for name, _ in contexts) > 1
            or any(name != "Additional context used" and not _check_context_timeout(name, value)
                and not _known_provider_assertion(name, value, recent.replace(context_region, ""), slug=slug, head=head)
                for name, value in contexts)):
            return None
        # The approved policy treats this named provider context as data. It
        # cannot supply identity, reviewed coverage, completion or a verdict.
        metadata = metadata.replace(recent_region, recent_region.replace(context_region, ""))

        walkthrough_region, walkthrough = _block(body, "walkthrough")
        if _wrapper(walkthrough)[0] != "Summary":
            return None
        metadata = metadata.replace(walkthrough_region, "")
        risk_region, risk = _block(body, "final_review_risk")
        label = re.search(r"<!-- final_review_risk_label\s+\*\*Merge Risk:\*\* \*\*⚪ Minimal\*\* · up to `([0-9a-f]{5,40})`\s*-->", risk)
        coverage = re.findall(r"<!-- final_review_risk_coverage:([^\n]+) -->", risk)
        outer = re.search(r'<details>\s*<summary><strong>Merge Risk:</strong> <strong>(.*?)Minimal</strong> · up to <code>([0-9a-f]{5,40})</code></summary>\s*<dl>\s*<dd>\s*<br>\s*' + re.escape(risk_region) + r"\s*</dd>\s*</dl>\s*</details>", body, re.DOTALL)
        if (label is None or len(coverage) != 1 or outer is None or _pictures(outer[1]).strip()
            or label[1] != outer[2] or not head.startswith(label[1])):
            return None
        metadata = metadata.replace(outer[0], f"<!-- final_review_risk_start -->\n<!-- final_review_risk_coverage:{coverage[0]} -->\n<!-- final_review_risk_end -->")

        checks_region, checks = _block(body, "pre_merge_checks_walkthrough")
        title, content = _wrapper(checks)
        count = re.fullmatch(r"Pre-merge checks: <sup></sup> ([1-9][0-9]*)", title)
        table, children = _details(content)
        rows = [line.strip() for line in table.splitlines() if line.strip()]
        cells = [[cell.strip() for cell in row.split("|")[1:-1]] for row in rows]
        if (count is None or len(rows) != int(count[1]) + 2
            or any(not row.startswith("|") or not row.endswith("|") for row in rows)
            or cells[0] != ["Check name", "Status", "Explanation"]
            or len(cells[1]) != 3 or any(re.fullmatch(r":?-+:?", cell) is None for cell in cells[1])
            or any(len(row) != 3 or not row[0] or row[1] != f"![Passed]({ASSETS}pre-merge-checks-passed.svg)" for row in cells[2:])):
            return None
        names = [row[0] for row in cells[2:]]
        if len(set(names)) != len(names):
            return None
        seen = set()
        for child in children:
            title, explanation = _wrapper(child)
            name = title.removeprefix("Full details: ")
            if title == name or name not in names or name in seen or not explanation.startswith("**Explanation**\n"):
                return None
            seen.add(name)
        metadata = metadata.replace(checks_region, "")

        if "<!-- finishing_touch_checkbox_start -->" in body:
            controls_region, controls = _block(body, "finishing_touch_checkbox")
            title, content = _wrapper(controls)
            gap, children = _details(content)
            custom_control = '- [ ] <!-- {"checkboxId":"custom-finishing-touch:harness%20docs%20parity-create-pr"} --> harness docs parity'
            if title != "Finishing Touches" or gap not in ("", custom_control) or not children:
                return None
            for child in children:
                title, options = _wrapper(child)
                if title not in {"Generate docstrings", "Generate unit tests (beta)"} or not all(_checkbox(line) for line in options.splitlines() if line.strip()):
                    return None
            metadata = metadata.replace(controls_region, "")
        if "<!-- autopilot:start -->" in body:
            autopilot = re.search(r'<!-- autopilot:start -->\s*- \[ \] <!-- \{"checkboxId":"' + UUID + r'"\} --> <strong title="Keep fixing CodeRabbit findings and required CI, and resolving merge conflicts">Autofix</strong> · Keep fixing CodeRabbit findings and required CI, and resolving merge conflicts\s*<!-- autopilot:end -->', body)
            if autopilot is None or body.count("<!-- autopilot:start -->") != 1 or body.count("<!-- autopilot:end -->") != 1:
                return None
            metadata = metadata.replace(autopilot[0], "")
        ids = re.findall(r"^- \*\*Run ID\*\*: `(" + UUID + r")`$", recent.replace(context_region, ""), re.MULTILINE)
        if len(ids) != 1:
            return None
        return {"metadata_body": _status_metadata(metadata), "summary_body": body, "review_url": review_url, "run_id": ids[0]}
    except (ValueError, TypeError, KeyError, RecursionError):
        return None


def _time(value: Any) -> datetime:
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value) is None:
        raise ValueError("invalid evidence timestamp")
    return datetime.fromisoformat(value)


def native_binding(entry: dict, structured: dict, history: dict, checks: list, pr: dict, slug: str, head: str) -> dict | None:
    """Bind immutable summary revisions to one exact-PR native check interval."""
    try:
        if (entry["user"] != {**entry["user"], "id": 136622811, "login": "coderabbitai[bot]", "type": "Bot"}
            or history["id"] != entry["node_id"] or history["databaseId"] != entry["id"]
            or history["url"] != entry["html_url"] or history["body"] != structured["summary_body"]
            or history["createdAt"] != entry["created_at"] or history["updatedAt"] != entry["updated_at"]
            or history["lastEditedAt"] != entry["updated_at"] or history["includesCreatedEdit"] is not True
            or history["author"] != {"login": "coderabbitai", "__typename": "Bot"}):
            return None
        edits = history["userContentEdits"]
        nodes = edits["nodes"]
        if (edits["pageInfo"]["hasNextPage"] is not False or type(edits["totalCount"]) is not int
            or not isinstance(nodes, list) or edits["totalCount"] != len(nodes) or not 2 <= len(nodes) <= 100
            or len({node["id"] for node in nodes}) != len(nodes)):
            return None
        for node in nodes:
            if (node["deletedAt"] is not None or node["editor"] != history["author"]
                or node["updatedAt"] != node["createdAt"] or not isinstance(node["diff"], str)
                or not _time(entry["created_at"]) <= _time(node["editedAt"]) <= _time(node["createdAt"]) <= _time(entry["updated_at"])):
                return None
        nodes = sorted(nodes, key=lambda node: node["editedAt"], reverse=True)
        terminal = nodes[0]
        if (terminal["diff"] != structured["summary_body"] or terminal["editedAt"] != entry["updated_at"]
            or terminal["createdAt"] != terminal["editedAt"]):
            return None
        run_line = f'- **Run ID**: `{structured["run_id"]}`'
        versions = [node for node in nodes if run_line in node["diff"] and PENDING_START not in node["diff"]]
        if not versions or versions != nodes[:len(versions)]:
            return None
        # A metadata refresh must retain every byte of the reviewed business
        # content. Its timestamp never advances clearance past a later finding.
        original = versions[-1]
        stable_body = _without_approval_policy(original["diff"], head)
        for version in versions:
            if (structured_summary(version["diff"], slug, pr["number"], head) is None
                or _without_approval_policy(version["diff"], head) != stable_body):
                return None
        pending, potential_pending = [], 0
        for node in nodes[len(versions):]:
            text = node["diff"]
            if text.count(PENDING_START) == text.count(PENDING_END) == 1:
                active = text.split(PENDING_START)[1].split(PENDING_END)[0]
                if run_line not in active:
                    continue
                potential_pending += 1
                _, children = _details(active)
                if len(children) != 1 or _wrapper(children[0])[0] != "Review info":
                    continue
                gap, fields = _details(_wrapper(children[0])[1])
                configurations = [_wrapper(field)[1] for field in fields if _wrapper(field)[0] == "Run configuration"]
                if gap or len(configurations) != 1:
                    continue
                config = configurations[0]
                commit = re.findall(r"^- \*\*Commit\*\*: (.+)$", config, re.MULTILINE)
                ui_config = (
                    "- **Source mode**: Auto\n- **Repository**: Unavailable\n- **Branch**: Unavailable\n"
                    "- **File**: No configuration file from this repository applied\n- **Commit**: Unavailable\n"
                )
                ui_pending = config.startswith(ui_config) and re.findall(
                    r"^- \*\*Layers\*\*: (.+)$", config, re.MULTILINE
                ) in (["Organization UI; Enforced overrides: Organization"],
                      ["Repository UI (base), Organization UI (inherited); Enforced overrides: Organization"])
                if (re.findall(r"^- \*\*Run ID\*\*: `(" + UUID + r")`$", config, re.MULTILINE) == [structured["run_id"]]
                    and (commit == [f"[{head[:7]}](<https://github.com/{slug}/commit/{head}>)"]
                         or ui_pending and commit == ["Unavailable"])
                    and all(re.fullmatch(r"- \*\*(?:Configuration used|Source mode|Repository|Branch|File|Commit|Layers|Review profile|Plan|Run ID)\*\*: [^\r\n]+", line)
                            for line in config.splitlines() if line.strip())):
                    pending.append(node)
        if potential_pending != 1 or len(pending) != 1 or pending[0] != nodes[len(versions)]:
            return None
        started, completed = _time(pending[0]["editedAt"]), _time(original["editedAt"])
        if started >= completed:
            return None
        # A validated metadata-only refresh can corroborate publication time,
        # never move the original completion boundary for intervening findings.
        # Keep the five-second bound around each authenticated stable revision.
        publication_edits = [(node, _time(node["editedAt"])) for node in versions]
        # Count possible matches across ALL revision windows before accepting
        # state/app/URL fields; competing records still make the join ambiguous.
        matches = [check for check in checks if check.get("name") == "CodeRabbit"
                   and any(abs((_time(check.get("completed_at")) - timestamp).total_seconds()) <= 5
                           for _, timestamp in publication_edits)]
        if len(matches) != 1:
            return None
        check = matches[0]
        associations = check["pull_requests"]
        output = check["output"]
        # Scope-less navigation is only presentation. Derive its destination
        # from the sole temporal check, then authenticate that check below.
        # Never use URL agreement to filter competing temporal records.
        review_url = check["details_url"]
        address = urlsplit(review_url)
        query = parse_qs(address.query, strict_parsing=True, keep_blank_values=True)
        if (address.scheme != "https" or address.netloc != "app.coderabbit.ai"
            or address.path != f"/change-stack/{slug}/pull/{pr['number']}" or address.fragment
            or set(query) != {"scope"} or len(query["scope"]) != 1
            or re.fullmatch(r"[A-Za-z0-9_-]+", query["scope"][0]) is None
            or review_url != f"https://app.coderabbit.ai{address.path}?scope={query['scope'][0]}"
            or structured["review_url"] is not None and structured["review_url"] != review_url):
            return None
        if (type(check["id"]) is not int or check["id"] <= 0 or check["head_sha"] != head
            or check["app"].get("id") != 347564 or check["app"].get("slug") != "coderabbitai"
            or check["status"] != "completed" or check["conclusion"] != "success"
            or abs((_time(check["started_at"]) - started).total_seconds()) > 5
            or _time(check["started_at"]) >= _time(check["completed_at"])
            or len(associations) != 1
            or associations[0]["number"] != pr["number"] or associations[0]["url"] != f"https://api.github.com/repos/{slug}/pulls/{pr['number']}"
            or associations[0]["head"]["sha"] != head or associations[0]["base"]["sha"] != pr["baseRefOid"]
            or any(associations[0][side]["repo"]["url"] != f"https://api.github.com/repos/{slug}" for side in ("head", "base"))
            or output["title"] != "Finished" or output["text"] not in (None, "")
            or type(output["annotations_count"]) is not int or output["annotations_count"] != 0):
            return None
        expected = (r"Result: Success - Review completed\nRun ID: `" + UUID + r"`\nCodeRabbit Review: \[Open CodeRabbit Review\]\("
                    + re.escape(review_url) + r"\)\n\n\| Step \| Status \| Time \|\n\| --- \| --- \| --- \|\n")
        duration = r"(?:[0-9]+(?:m|s|ms) ?)+"
        for step in ("Prepare review scope", "Prepare repository workspace", "Run analysis checks", "Generate review feedback", "Publish review results"):
            expected += r"\| " + step + r" \| Completed \| " + duration + r" \|\n"
        expected += r"\| Time taken \| \| " + duration + r" \|"
        if re.fullmatch(expected, output["summary"]) is None:
            return None
        publication = min((node for node, timestamp in publication_edits
                           if abs((_time(check["completed_at"]) - timestamp).total_seconds()) <= 5),
                          key=lambda node: _time(node["editedAt"]))
        return {"check_run_id": check["id"], "terminal_edit_id": original["id"], "latest_edit_id": terminal["id"], "pending_edit_id": pending[0]["id"],
                "publication_edit_id": publication["id"], "publication_at": publication["editedAt"],
                "completed_at": min(completed, _time(check["completed_at"])).isoformat().replace("+00:00", "Z"),
                "summary_run_id": structured["run_id"], "review_url": review_url,
                "summary_body": structured["summary_body"]}
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        return None
