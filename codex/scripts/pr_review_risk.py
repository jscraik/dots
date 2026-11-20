"""Classify complete committed-path records for the readiness review gate.

This pure helper neither collects a diff nor grants readiness. Its caller must
supply every record from a validated committed diff, including deletions and
both sides of renames, then enforce independent reviews and all other gates.
The readiness consumer collects committed records and enforces this quorum.
"""
from __future__ import annotations

import re
import unicodedata
from fnmatch import fnmatchcase

HIGH_RISK_COMPONENTS = frozenset({
    ".agents", ".agent", ".codex", ".github", ".circleci", "agents", "codex",
    "auth", "authentication", "authorization", "security", "permissions",
    "policy", "policies", "governance", "instructions", "hooks", "rules",
    "migrations", "deploy", "deployment", "infra", "automations", "requirements", "constraints",
})
HIGH_RISK_NAMES = frozenset({
    "agents.md", "claude.md", "gemini.md", "codestyle.md", "contributing.md",
    "security.md", "codeowners", "makefile", "dockerfile", "harness.contract.json",
    "package.json", "package-lock.json", "pnpm-lock.yaml", "pnpm-workspace.yaml", "yarn.lock",
    "pyproject.toml", "uv.lock", "poetry.lock", "cargo.toml", "cargo.lock",
    "go.mod", "go.sum", "gemfile", "gemfile.lock", ".env", "mise.toml", ".mise.toml",
    "package.swift", "package.resolved", "composer.json", "composer.lock",
    "setup.py", "setup.cfg", "build.gradle", "build.gradle.kts", "pom.xml",
    ".coderabbit.yaml", ".coderabbit.yml",
})
HIGH_RISK_PATH_SUFFIXES = ("mise/config.toml", "scripts/link-configs.sh")
HIGH_RISK_WORDS = HIGH_RISK_COMPONENTS | frozenset({
    "permission", "readiness", "review", "approval", "credential", "credentials",
    "secret", "secrets", "credential", "credentials",
    "workflow", "signing", "cryptography", "identity", "privilege", "privileges",
    "release", "publish", "deployment", "runner",
    "oauth", "oauth2", "login", "password", "jwt",
    "claude", "gemini",
})
ORDINARY_PATTERNS = (
    "*.md", "*.rst", "*.adoc", "*.png", "*.jpg", "*.jpeg",
    "*.webp", "*.gif", "*.ico",
    "*.py", "*.js", "*.jsx", "*.ts", "*.tsx", "*.mjs", "*.cjs",
    "*.swift", "*.rs", "*.go", "*.java", "*.kt", "*.kts", "*.rb",
    "*.c", "*.h", "*.cc", "*.cpp", "*.hpp", "*.cs", "*.php",
    "*.sh", "*.bash", "*.zsh", "*.sql", "*.html", "*.css", "*.scss",
    "*.vue", "*.svelte", "*.json", "*.yaml", "*.yml", "*.toml", "*.txt",
)
GIT_FILE_MODES = frozenset({"000000", "100644", "100755", "120000", "160000"})


def committed_review_requirement(records: object) -> dict[str, object]:
    """Validate transport records and classify risk without reviewing content.

    Empty input is high risk. Malformed records fail closed rather than being
    discarded. Known source, tests, documentation and configuration are ordinary
    unless a consequential path, dependency manifest or mode change escalates
    them. This path classifier does not replace the independent content review.
    """
    if not isinstance(records, list):
        raise TypeError("committed-path records must be an array")
    seen: set[str] = set()
    high_risk: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != {"path", "old_mode", "new_mode"}:
            raise ValueError("committed-path record must contain path and both modes")
        path = record["path"]
        old_mode, new_mode = record["old_mode"], record["new_mode"]
        if not isinstance(path, str) or not path or any(part in {"", ".", ".."} for part in path.split("/")) or "\0" in path:
            raise ValueError("committed path must be a normalized repository-relative path")
        path.encode("utf-8", errors="strict")
        if path in seen:
            raise ValueError("duplicate committed path")
        seen.add(path)
        if not isinstance(old_mode, str) or not isinstance(new_mode, str) or old_mode not in GIT_FILE_MODES or new_mode not in GIT_FILE_MODES or old_mode == new_mode == "000000":
            raise ValueError("committed path has invalid file modes")
        lowered = path.casefold()
        components = lowered.split("/")
        separated = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", path)
        # Keep mixed-case words such as OAuth2 alongside acronym splits
        # that expose protected terms in names such as APIAuth.
        acronym_split = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", separated)
        words = set(re.split(r"[^a-z0-9]+", f"{separated} {acronym_split}".casefold()))
        protected = bool(set(components) & HIGH_RISK_COMPONENTS) or components[-1] in HIGH_RISK_NAMES
        protected = protected or any(lowered == suffix or lowered.endswith("/" + suffix)
                                     for suffix in HIGH_RISK_PATH_SUFFIXES)
        protected = protected or bool(words & HIGH_RISK_WORDS)
        protected = protected or any(fnmatchcase(components[-1], pattern) for pattern in (
            "requirements*.txt", "constraints*.txt", "*.lock", ".env.*",
        ))
        regular_modes = {"000000", "100644", "100755"}
        special = old_mode not in regular_modes or new_mode not in regular_modes
        special = special or (new_mode == "100755" and old_mode != "100755")
        ordinary = any(fnmatchcase(lowered, pattern) for pattern in ORDINARY_PATTERNS)
        misleading = any(unicodedata.category(char) in {"Cc", "Cf", "Zl", "Zp"} for char in path)
        if protected or special or not ordinary or "\\" in path or misleading:
            high_risk.add(path)
    high = bool(high_risk) or not records
    return {
        "risk_tier": "high" if high else "ordinary",
        "required_bot_review_count": 2 if high else 1,
        "high_risk_paths": sorted(high_risk),
        "risk_basis": "complete committed diff; protected and unclassified paths require two bots",
    }
