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
                 and re.fullmatch(r"utg-output-choice-group-[1-9][0-9]*", data["radioGroupId"]) is not None))


def structured_summary(body: str, slug: str, number: int, head: str) -> dict[str, str] | None:
    """Adapt only the complete observed structured report, retaining its raw text."""
    try:
        if (not isinstance(body, str) or len(body) > 262144 or PENDING_START in body
            or re.search(r"Actionable comments posted:|Outside diff range comments|cr-indicator-types:potential_issue|review (?:incomplete|skipped|paused)|files skipped", body, re.IGNORECASE)):
            return None
        failure_start = "<!-- This is an auto-generated comment: all tool run failures by coderabbit.ai -->"
        failure_end = "<!-- end of auto-generated comment: all tool run failures by coderabbit.ai -->"
        if failure_start in body or failure_end in body:
            failure = re.search(re.escape(failure_start) + r"(.*?)" + re.escape(failure_end), body, re.DOTALL)
            if body.count(failure_start) != 1 or body.count(failure_end) != 1 or failure is None or failure[1].strip():
                return None
        metadata = body
        nav_region, nav = _block(body, "review_stack_entry")
        link = re.fullmatch(r'<a href="([^"<>]+)">(?:Explain Change →)?</a>', _pictures(nav))
        if link is None:
            return None
        address = urlsplit(unescape(link[1]))
        query = parse_qs(address.query, strict_parsing=True)
        if (address.scheme != "https" or address.netloc != "app.coderabbit.ai"
            or address.path != f"/change-stack/{slug}/pull/{number}" or address.fragment
            or set(query) != {"scope", "cs_source"} or query["cs_source"] != ["review_comment"]
            or len(query["scope"]) != 1 or re.fullmatch(r"[A-Za-z0-9_-]+", query["scope"][0]) is None):
            return None
        review_url = f"https://app.coderabbit.ai{address.path}?scope={query['scope'][0]}"
        metadata = metadata.replace(nav_region, "")

        recent_region, recent = _block(body, "recent_review")
        context_region, context = _block(recent, "review_details")
        title, content = _wrapper(context)
        gap, children = _details(content)
        if title not in {"Recent review details", "📜 Recent review details"} or gap or len(children) != 1 or _wrapper(children[0])[0] != "Additional context used":
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
            if title != "Finishing Touches" or gap or not children:
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
        return {"metadata_body": metadata, "summary_body": body, "review_url": review_url, "run_id": ids[0]}
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
        # Exactly one terminal version for this run. A later edit cannot reuse
        # the run ID to move a no-findings decision past an intervening finding.
        if sum(run_line in node["diff"] and PENDING_START not in node["diff"] for node in nodes) != 1:
            return None
        pending, potential_pending = [], 0
        for node in nodes[1:]:
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
                if (re.findall(r"^- \*\*Run ID\*\*: `(" + UUID + r")`$", config, re.MULTILINE) == [structured["run_id"]]
                    and re.findall(r"^- \*\*Commit\*\*: (.+)$", config, re.MULTILINE) == [f"[{head[:7]}](<https://github.com/{slug}/commit/{head}>)"]
                    and all(re.fullmatch(r"- \*\*(?:Configuration used|Source mode|Repository|Branch|File|Commit|Layers|Review profile|Plan|Run ID)\*\*: [^\r\n]+", line)
                            for line in config.splitlines() if line.strip())):
                    pending.append(node)
        if potential_pending != 1 or len(pending) != 1 or pending[0] != nodes[1]:
            return None
        started, completed = _time(pending[0]["editedAt"]), _time(terminal["editedAt"])
        if started >= completed:
            return None
        # Count possible temporal matches before accepting state/app fields;
        # incomplete competing records cannot be filtered out of ambiguity.
        matches = [check for check in checks if check.get("name") == "CodeRabbit"
                   and abs((_time(check.get("completed_at")) - completed).total_seconds()) <= 5]
        if len(matches) != 1:
            return None
        check = matches[0]
        associations = check["pull_requests"]
        output = check["output"]
        if (type(check["id"]) is not int or check["id"] <= 0 or check["head_sha"] != head
            or check["app"].get("id") != 347564 or check["app"].get("slug") != "coderabbitai"
            or check["status"] != "completed" or check["conclusion"] != "success"
            or abs((_time(check["started_at"]) - started).total_seconds()) > 5
            or _time(check["started_at"]) >= _time(check["completed_at"])
            or check["details_url"] != structured["review_url"] or len(associations) != 1
            or associations[0]["number"] != pr["number"] or associations[0]["url"] != f"https://api.github.com/repos/{slug}/pulls/{pr['number']}"
            or associations[0]["head"]["sha"] != head or associations[0]["base"]["sha"] != pr["baseRefOid"]
            or any(associations[0][side]["repo"]["url"] != f"https://api.github.com/repos/{slug}" for side in ("head", "base"))
            or output["title"] != "Finished" or output["text"] not in (None, "")
            or type(output["annotations_count"]) is not int or output["annotations_count"] != 0):
            return None
        expected = (r"Result: Success - Review completed\nRun ID: `" + UUID + r"`\nCodeRabbit Review: \[Open CodeRabbit Review\]\("
                    + re.escape(structured["review_url"]) + r"\)\n\n\| Step \| Status \| Time \|\n\| --- \| --- \| --- \|\n")
        duration = r"(?:[0-9]+(?:m|s|ms) ?)+"
        for step in ("Prepare review scope", "Prepare repository workspace", "Run analysis checks", "Generate review feedback", "Publish review results"):
            expected += r"\| " + step + r" \| Completed \| " + duration + r" \|\n"
        expected += r"\| Time taken \| \| " + duration + r" \|"
        if re.fullmatch(expected, output["summary"]) is None:
            return None
        return {"check_run_id": check["id"], "terminal_edit_id": terminal["id"], "pending_edit_id": pending[0]["id"],
                "completed_at": min(completed, _time(check["completed_at"])).isoformat().replace("+00:00", "Z"),
                "summary_run_id": structured["run_id"], "review_url": structured["review_url"],
                "summary_body": structured["summary_body"]}
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        return None
