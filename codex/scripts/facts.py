"""Fact registry with freshness tracking and provenance.

This module provides a self-auditing evidence ledger for the insights
report system. Every piece of data that appears in a report must have:
- A source (where it came from)
- An observation time (when the underlying data was captured)
- A TTL (how long it remains fresh)
- A derivation path (how it was computed, if derived)

The core principle: NOTHING renders without source + observed_at + ttl.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from report_security import sanitize_export


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


SOURCE_LIVE_LOCAL = "live_local"
SOURCE_LIVE_EXTERNAL = "live_external"
SOURCE_DERIVED = "derived"
SOURCE_CURATED = "curated"


@dataclass
class Fact:
    """A single piece of evidence with full provenance."""

    key: str
    value: Any
    source_type: str
    source_ref: str
    observed_at: datetime
    fetched_at: datetime
    ttl_seconds: int
    derivation: str | None = None
    confidence: float = 1.0
    cache_status: str = "live"

    def is_fresh(self, now: datetime | None = None) -> bool:
        """Check if this fact is within its freshness window."""
        if now is None:
            now = datetime.now(UTC)
        return now - self.observed_at <= timedelta(seconds=self.ttl_seconds)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        d = asdict(self)
        d["observed_at"] = self.observed_at.isoformat()
        d["fetched_at"] = self.fetched_at.isoformat()
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Fact:
        """Create a Fact from a dictionary."""
        data = dict(data)
        if isinstance(data.get("observed_at"), str):
            data["observed_at"] = datetime.fromisoformat(data["observed_at"])
        if isinstance(data.get("fetched_at"), str):
            data["fetched_at"] = datetime.fromisoformat(data["fetched_at"])
        return cls(**data)


DEFAULT_TTLS = {
    SOURCE_LIVE_LOCAL: 3600,
    SOURCE_LIVE_EXTERNAL: 86400,
    SOURCE_DERIVED: 1800,
    SOURCE_CURATED: 604800,
}


class FactRegistry:
    """Registry of facts with freshness tracking and invariant validation."""

    def __init__(self, snapshot_dir: Path | None = None):
        self._facts: dict[str, Fact] = {}
        self._invariant_checks: list[Callable[[FactRegistry], list[str]]] = []
        self._derivation_log: list[str] = []
        self._snapshot_dir = snapshot_dir
        self._now = datetime.now(UTC)

    def now(self) -> datetime:
        """Get the current reference time for freshness checks."""
        return self._now

    def register(
        self,
        key: str,
        value: Any,
        source_type: str,
        source_ref: str,
        observed_at: datetime | None = None,
        ttl_seconds: int | None = None,
        derivation: str | None = None,
        confidence: float = 1.0,
    ) -> Fact:
        """Register a new fact with provenance."""
        if observed_at is None:
            observed_at = self._now
        if ttl_seconds is None:
            ttl_seconds = DEFAULT_TTLS.get(source_type, 3600)
        fact = Fact(
            key=key,
            value=value,
            source_type=source_type,
            source_ref=source_ref,
            observed_at=observed_at,
            fetched_at=self._now,
            ttl_seconds=ttl_seconds,
            derivation=derivation,
            confidence=confidence,
        )
        if fact.is_fresh(self._now):
            fact.cache_status = "live"
        else:
            fact.cache_status = "stale"
        self._facts[key] = fact
        return fact

    def register_derived(
        self,
        key: str,
        value: Any,
        derivation: str,
        depends_on: list[str],
        ttl_seconds: int | None = None,
    ) -> Fact:
        """Register a derived fact that depends on other facts.

        The derived fact is only fresh if all dependencies are fresh.
        """
        all_fresh = True
        min_observed = self._now
        for dep_key in depends_on:
            dep = self._facts.get(dep_key)
            if dep is None:
                all_fresh = False
                self._derivation_log.append(f"Missing dependency: {dep_key} for {key}")
            elif not dep.is_fresh(self._now):
                all_fresh = False
                self._derivation_log.append(f"Stale dependency: {dep_key} for {key}")
            else:
                min_observed = min(min_observed, dep.observed_at)
        if ttl_seconds is None:
            ttl_seconds = DEFAULT_TTLS.get(SOURCE_DERIVED, 1800)
        cache_status = "live" if all_fresh else "stale"
        fact = Fact(
            key=key,
            value=value,
            source_type=SOURCE_DERIVED,
            source_ref=derivation,
            observed_at=min_observed if all_fresh else self._now,
            fetched_at=self._now,
            ttl_seconds=ttl_seconds,
            derivation=derivation,
            confidence=1.0 if all_fresh else 0.5,
            cache_status=cache_status,
        )
        self._facts[key] = fact
        return fact

    def register_curated(
        self, key: str, value: Any, source_ref: str, notes: str | None = None
    ) -> Fact:
        """Register hand-authored guidance (explicitly NOT live data)."""
        return self.register(
            key=key,
            value=value,
            source_type=SOURCE_CURATED,
            source_ref=source_ref,
            observed_at=self._now,
            ttl_seconds=DEFAULT_TTLS[SOURCE_CURATED],
            derivation=f"curated: {notes}" if notes else "curated",
        )

    def get(self, key: str) -> Fact | None:
        """Get a fact by key."""
        return self._facts.get(key)

    def get_value(self, key: str, default: Any = None) -> Any:
        """Get a fact's value, or default if missing/stale."""
        fact = self._facts.get(key)
        if fact is None:
            return default
        if not fact.is_fresh(self._now):
            return default
        return fact.value

    def get_fresh_facts(self) -> dict[str, Fact]:
        """Get all facts that are currently fresh."""
        return {k: f for k, f in self._facts.items() if f.is_fresh(self._now)}

    def get_stale_facts(self) -> dict[str, Fact]:
        """Get all facts that are stale."""
        return {k: f for k, f in self._facts.items() if not f.is_fresh(self._now)}

    def add_invariant_check(self, check: Callable[[FactRegistry], list[str]]) -> None:
        """Add an invariant validation function.

        Invariant checks should return a list of violation messages.
        Empty list means all invariants pass.
        """
        self._invariant_checks.append(check)

    def validate_invariants(self) -> list[str]:
        """Run all invariant checks and return violations."""
        violations: list[str] = []
        for check in self._invariant_checks:
            try:
                violations.extend(check(self))
            except Exception as e:  # noqa: BLE001 - MIG-HELPER-1: preserve callback-to-blocking-violation contract; instructions/migration-scope.md#helper-boundary-decisions
                violations.append(f"Invariant check failed: {e}")
        return violations

    def snapshot(self, output_dir: Path) -> dict[str, Path]:
        """Write snapshot files for auditability.

        Returns dict of {purpose: path} for files written.
        """
        _fixture_scope().output(output_dir).mkdir(parents=True, exist_ok=True)
        paths = {}

        def write_export(name: str, payload: object) -> None:
            path = output_dir / f"{name}.json"
            _fixture_scope().output(path).write_text(
                json.dumps(sanitize_export(payload), indent=2), encoding="utf-8"
            )
            paths[name] = path

        write_export("facts", {k: f.to_dict() for k, f in self._facts.items()})
        sources: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "refs": []}
        )
        for fact in self._facts.values():
            sources[fact.source_type]["count"] += 1
            if len(sources[fact.source_type]["refs"]) < 10:
                sources[fact.source_type]["refs"].append(fact.source_ref)
        write_export("sources", sources)
        fresh = self.get_fresh_facts()
        stale = self.get_stale_facts()
        freshness = {
            "total_facts": len(self._facts),
            "fresh_count": len(fresh),
            "stale_count": len(stale),
            "fresh_keys": list(fresh.keys()),
            "stale_keys": list(stale.keys()),
            "invariant_violations": self.validate_invariants(),
            "derivation_log": self._derivation_log[-20:],
        }
        write_export("freshness", freshness)
        return paths

    def to_dict(self) -> dict[str, Any]:
        """Export full registry as dictionary."""
        return sanitize_export(
            {
                "facts": {k: f.to_dict() for k, f in self._facts.items()},
                "invariant_violations": self.validate_invariants(),
                "fresh_count": len(self.get_fresh_facts()),
                "stale_count": len(self.get_stale_facts()),
            }
        )


def session_count_invariant(registry: FactRegistry) -> list[str]:
    """Invariant: report-window session counts cannot exceed analyzed_sessions."""
    violations = []
    analyzed = registry.get_value("sessions.analyzed_count", 0)
    exempt_keys = {"sessions.discovered_count"}
    for key, fact in registry._facts.items():
        if key in exempt_keys:
            continue
        if (
            "session" in key.lower()
            and isinstance(fact.value, (int, float))
            and (fact.value > analyzed > 0)
        ):
            violations.append(
                f"Session-labeled count {key}={fact.value} exceeds analyzed_sessions={analyzed}"
            )
    return violations


def no_missing_sources_invariant(registry: FactRegistry) -> list[str]:
    """Invariant: no fact may have empty source_ref."""
    violations = []
    for key, fact in registry._facts.items():
        if not fact.source_ref or not fact.source_ref.strip():
            violations.append(f"Fact {key} has empty source_ref")
    return violations


def derived_freshness_invariant(registry: FactRegistry) -> list[str]:
    """Invariant: derived facts cannot be fresher than their dependencies."""
    violations = []
    for key, fact in registry._facts.items():
        if fact.source_type != SOURCE_DERIVED:
            continue
        if not fact.derivation:
            continue
        if "depends_on:" in fact.derivation:
            dep_str = fact.derivation.split("depends_on:")[1].strip()
            dep_keys = [k.strip() for k in dep_str.split(",")]
            for dep_key in dep_keys:
                dep = registry._facts.get(dep_key)
                if dep and dep.observed_at > fact.observed_at:
                    violations.append(
                        f"Derived fact {key} is fresher than dependency {dep_key}"
                    )
    return violations


def count_sessions_with_facts(
    registry: FactRegistry,
    sessions: list[Any],
    counter_func: Callable[[Any], dict[str, int]],
    base_key: str = "sessions",
) -> dict[str, Fact]:
    """Count sessions by categories, producing properly grounded facts.

    Args:
        registry: The fact registry
        sessions: List of session data
        counter_func: Function that takes a session and returns {category: count}
        base_key: Base key for the facts

    Returns:
        Dict of category -> Fact
    """
    registry.register(
        key=f"{base_key}.analyzed_count",
        value=len(sessions),
        source_type=SOURCE_LIVE_LOCAL,
        source_ref="sessions/*.jsonl",
    )
    totals: dict[str, int] = defaultdict(int)
    for session in sessions:
        counts = counter_func(session)
        for cat, count in counts.items():
            totals[cat] += count
    facts = {}
    for cat, total in totals.items():
        safe_key = cat.lower().replace(" ", "_").replace("/", "_")
        fact = registry.register_derived(
            key=f"{base_key}.{safe_key}",
            value=total,
            derivation=f"count of {cat} across sessions, depends_on: {base_key}.analyzed_count",
            depends_on=[f"{base_key}.analyzed_count"],
        )
        facts[cat] = fact
    return facts


if __name__ == "__main__":
    _fixture_scope().admit_file(__file__)
    import tempfile

    registry = FactRegistry()
    registry.register(
        key="sessions.analyzed_count",
        value=375,
        source_type=SOURCE_LIVE_LOCAL,
        source_ref="~/.codex/sessions/**/*.jsonl",
    )
    registry.register_derived(
        key="sessions.git_operations",
        value=7821,
        derivation="keyword occurrence count, depends_on: sessions.analyzed_count",
        depends_on=["sessions.analyzed_count"],
    )
    registry.register_curated(
        key="recommendations.future_features",
        value=["MCP Server Ecosystem", "Custom Slash Commands"],
        source_ref="codex/prompts/insights.md",
        notes="hand-curated list of features to watch",
    )
    registry.add_invariant_check(session_count_invariant)
    registry.add_invariant_check(no_missing_sources_invariant)
    violations = registry.validate_invariants()
    if violations:
        print("Invariant violations:")
        for v in violations:
            print(f"  - {v}")
    else:
        print("All invariants pass!")
    print(f"\nTotal facts: {len(registry._facts)}")
    print(f"Fresh facts: {len(registry.get_fresh_facts())}")
    print(f"Stale facts: {len(registry.get_stale_facts())}")
    with tempfile.TemporaryDirectory() as tmpdir:
        paths = registry.snapshot(Path(tmpdir))
        print("\nSnapshot files written:")
        for purpose, path in paths.items():
            print(f"  {purpose}: {path}")
