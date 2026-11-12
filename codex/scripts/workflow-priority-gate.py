"""Summarize open workflow-improvement priority gates for Codex session start."""

from __future__ import annotations

from migration_scope import require_policy_path, require_policy_scope

require_policy_scope()

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BOOTSTRAP_P0: tuple[dict[str, str], ...] = ()
SERVICE = "workflow-priority-gate"
CLOSED_STATUSES = {
    "done",
    "closed",
    "complete",
    "completed",
    "cancelled",
    "canceled",
    "local-proof-complete",
    "local-proof-implemented",
    "local-proof-pass",
    "local-proof-proved",
}


@dataclass(frozen=True)
class GateItem:
    ticket_id: str
    title: str
    priority: str
    repo: str
    proof_required: str
    first_action: str
    source: str

    def as_dict(self) -> dict[str, str]:
        return {
            "ticket_id": self.ticket_id,
            "title": self.title,
            "priority": self.priority,
            "repo": self.repo,
            "proof_required": self.proof_required,
            "first_action": self.first_action,
            "source": self.source,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report workflow-improvement P0 gates for session-start hooks.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Codex subtree root. Defaults to this script's codex directory.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Explicit workflow improvement report or ledger JSON file.",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=6,
        help="Maximum open P0 items to include in the human summary.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit only the machine-readable JSON gate result.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Alias for the default non-mutating behavior.",
    )
    return parser.parse_args()


def candidate_reports(repo_root: Path, explicit_report: Path | None) -> list[Path]:
    candidates: list[Path] = []
    env_report = os.environ.get("CODEX_WORKFLOW_PRIORITY_GATE_REPORT", "").strip()
    if explicit_report is not None:
        candidates.append(explicit_report)
    if env_report:
        candidates.append(Path(env_report))

    report_dir = repo_root / "reports" / "workflow-improvements"
    if report_dir.is_dir():
        candidates.extend(
            sorted(report_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        )

    return candidates


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(data, dict):
        return data
    return None


def coerce_item(raw: dict[str, Any], source: str, implied_priority: str | None = None) -> GateItem | None:
    priority = str(raw.get("priority") or raw.get("severity") or implied_priority or "").upper()
    status = str(raw.get("status") or raw.get("state") or "open").lower()
    if priority != "P0" or status in CLOSED_STATUSES:
        return None

    ticket_id = str(raw.get("ticket_id") or raw.get("id") or raw.get("linear_id") or "untracked")
    title = str(raw.get("title") or raw.get("summary") or "Untitled workflow gate")
    repo = str(raw.get("repo") or raw.get("project") or raw.get("target_repo") or "unknown")
    proof_required = str(raw.get("proof_required") or raw.get("proof_command") or raw.get("next_check") or "not specified")
    first_action = str(raw.get("first_action") or raw.get("next_action") or raw.get("tomorrow_first_action") or title)

    return GateItem(
        ticket_id=ticket_id,
        title=title,
        priority="P0",
        repo=repo,
        proof_required=proof_required,
        first_action=first_action,
        source=source,
    )


def items_from_report(data: dict[str, Any], source: str) -> list[GateItem]:
    raw_items: list[Any] = []
    items: list[GateItem] = []
    for key in ("p0", "p0_items", "queue", "tickets", "items", "candidates"):
        value = data.get(key)
        if isinstance(value, list):
            raw_items.extend(value)
    priorities = data.get("priorities")
    if isinstance(priorities, dict):
        for bucket, value in priorities.items():
            if isinstance(value, list):
                for raw in value:
                    if isinstance(raw, dict):
                        item = coerce_item(raw, source, implied_priority=str(bucket))
                        if item is not None:
                            items.append(item)

    for raw in raw_items:
        if isinstance(raw, dict):
            item = coerce_item(raw, source)
            if item is not None:
                items.append(item)
    return items


def find_gate_items(repo_root: Path, explicit_report: Path | None) -> tuple[list[GateItem], list[str]]:
    checked_sources: list[str] = []
    for report in candidate_reports(repo_root, explicit_report):
        checked_sources.append(str(report))
        data = load_json(report)
        if data is None:
            continue
        items = items_from_report(data, str(report))
        return items, checked_sources

    bootstrap_items = [
        GateItem(priority="P0", source="bootstrap-linear-queue", **item)
        for item in BOOTSTRAP_P0
    ]
    return bootstrap_items, checked_sources


def build_result(items: list[GateItem], checked_sources: list[str], max_items: int) -> dict[str, Any]:
    visible_items = items[: max(max_items, 0)]
    status = "blocked_by_p0" if items else "pass"
    first_action = visible_items[0].first_action if visible_items else "No open P0 workflow gate found."
    return {
        "service": SERVICE,
        "schema_version": "workflow-priority-gate/v1",
        "gate_status": status,
        "checked_sources": checked_sources,
        "p0_count": len(items),
        "p0_items": [item.as_dict() for item in visible_items],
        "first_action": first_action,
        "claims_boundary": {
            "live_checked": checked_sources,
            "fallback": "bootstrap-linear-queue" if items and all(item.source == "bootstrap-linear-queue" for item in items) else None,
            "does_not_prove": [
                "Linear issue status was not refreshed by this local hook.",
                "Hosted PR, CI, review, tracker, and merge-readiness lanes remain separate.",
            ],
        },
    }


def human_summary(result: dict[str, Any]) -> str:
    if result["gate_status"] == "pass":
        return f"service:{SERVICE} | Workflow priority gate: pass. No open P0 workflow gate found."

    lines = [
        f"service:{SERVICE} | Workflow priority gate: blocked_by_p0 ({result['p0_count']} open P0 item(s)).",
        f"First action: {result['first_action']}",
        "Open P0 workflow guardrails:",
    ]
    for item in result["p0_items"]:
        lines.append(
            f"- {item['ticket_id']}: {item['title']} | repo: {item['repo']} | proof: {item['proof_required']}"
        )
    lines.append("Assess whether the reported guardrail blocks the named outcome; pause only dependent actions and continue independent authorized work. Do not adopt unrelated repairs without authority.")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    require_policy_path(args.repo_root)
    if args.report is not None:
        require_policy_path(args.report)
    items, checked_sources = find_gate_items(args.repo_root.resolve(), args.report)
    result = build_result(items, checked_sources, args.max_items)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(human_summary(result))
        print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
