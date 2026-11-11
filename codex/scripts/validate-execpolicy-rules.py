"""Validate Codex execpolicy rules and the admin-enforced requirements baseline."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

from migration_scope import require_disposable_scope, require_fixture_path

try:
    import tomllib
except ModuleNotFoundError:
    try:
        tomllib = importlib.import_module("tomli")
    except ModuleNotFoundError:
        tomllib = None
REPO_ROOT = Path(__file__).resolve().parent.parent
RULES_DIR = REPO_ROOT / "rules"
REQUIREMENTS_PATH = REPO_ROOT / "requirements.toml"
require_disposable_scope()
require_fixture_path(REPO_ROOT)
require_fixture_path(RULES_DIR)
require_fixture_path(REQUIREMENTS_PATH)


def fixture_literal(value: str) -> str:
    def replace(part: str) -> str:
        return part.replace("@CODEX_SOURCE@", str(REPO_ROOT)).replace(
            "@HOME@", str(Path.home())
        )

    if value.startswith("cd "):
        # These strings are inputs to the matcher, never shell commands to run.
        return (
            "cd "
            + shlex.quote(replace(value.split(" ", 2)[1]))
            + " "
            + value.split(" ", 2)[2]
        )
    return replace(value)


REAL_LEASE_OID = "0123456789abcdef0123456789abcdef01234567"
EFFECTIVE_RULES_SENTINEL = "<effective-rules>"
CASES = [
    {
        "name": "effective rules leave inline Python approval-governed",
        "rules": [EFFECTIVE_RULES_SENTINEL],
        "cmd": ["python3", "-c", "print('fixture')"],
        "expected_decision": None,
    },
    {
        "name": "effective rules leave find execution approval-governed",
        "rules": [EFFECTIVE_RULES_SENTINEL],
        "cmd": ["find", ".", "-exec", "echo", "{}", ";"],
        "expected_decision": None,
    },
    {
        "name": "effective rules leave ordinary find approval-governed",
        "rules": [EFFECTIVE_RULES_SENTINEL],
        "cmd": ["find", ".", "-name", "*.md"],
        "expected_decision": None,
    },
    {
        "name": "effective rules leave ordinary fd approval-governed",
        "rules": [EFFECTIVE_RULES_SENTINEL],
        "cmd": ["fd", ".", "src"],
        "expected_decision": None,
    },
    {
        "name": "effective rules allow named Python tests",
        "rules": [EFFECTIVE_RULES_SENTINEL],
        "cmd": ["python3", "-m", "pytest"],
        "expected_decision": "allow",
    },
    {
        "name": "effective rules leave arbitrary Python approval-governed",
        "rules": [EFFECTIVE_RULES_SENTINEL],
        "cmd": ["python3", "script.py"],
        "expected_decision": None,
    },
    {
        "name": "effective rules allow aggregate check",
        "rules": [EFFECTIVE_RULES_SENTINEL],
        "cmd": ["pnpm", "check"],
        "expected_decision": "allow",
    },
    {
        "name": "effective rules leave arbitrary package scripts approval-governed",
        "rules": [EFFECTIVE_RULES_SENTINEL],
        "cmd": ["pnpm", "run", "custom"],
        "expected_decision": None,
    },
    {
        "name": "effective rules leave find deletion approval-governed",
        "rules": [EFFECTIVE_RULES_SENTINEL],
        "cmd": ["find", ".", "-delete"],
        "expected_decision": None,
    },
    {
        "name": "effective rules leave fd execution approval-governed",
        "rules": [EFFECTIVE_RULES_SENTINEL],
        "cmd": ["fd", ".", "--exec", "echo", "{}"],
        "expected_decision": None,
    },
    {
        "name": "effective rules leave routine file discovery approval-governed",
        "rules": [EFFECTIVE_RULES_SENTINEL],
        "cmd": ["rg", "--files"],
        "expected_decision": None,
    },
    {
        "name": "foundation allows pwd",
        "rules": ["foundation.rules"],
        "cmd": ["pwd"],
        "expected_decision": "allow",
    },
    {
        "name": "foundation does not auto-allow env",
        "rules": ["foundation.rules"],
        "cmd": ["env"],
        "expected_decision": None,
    },
    {
        "name": "default does not retain historical exact allows",
        "rules": ["default.rules"],
        "cmd": ["zsh", "-lc", "rm -rf apple"],
        "expected_decision": None,
    },
    {
        "name": "default allows only the fixed-output FIFO canary",
        "rules": ["default.rules"],
        "cmd": [
            "bash",
            fixture_literal("@CODEX_SOURCE@/scripts/run-auth-backed.sh"),
            "--env-file",
            fixture_literal("@HOME@/.codex/.env"),
            "--canary",
            "OLLAMA_API_KEY",
        ],
        "expected_decision": "allow",
        "justification_contains": "fixed-output Ollama auth canary",
    },
    {
        "name": "default allows the fixed-output CircleCI FIFO canary",
        "rules": ["default.rules"],
        "cmd": [
            "bash",
            fixture_literal("@CODEX_SOURCE@/scripts/run-auth-backed.sh"),
            "--env-file",
            fixture_literal("@HOME@/.codex/.env"),
            "--canary",
            "CIRCLECI_CLI_TOKEN",
        ],
        "expected_decision": "allow",
        "justification_contains": "fixed-output CircleCI auth canary",
    },
    {
        "name": "default does not allow implicit-route canary",
        "rules": ["default.rules"],
        "cmd": [
            "bash",
            fixture_literal("@CODEX_SOURCE@/scripts/run-auth-backed.sh"),
            "--canary",
            "OLLAMA_API_KEY",
        ],
        "expected_decision": None,
    },
    {
        "name": "default does not bypass policy for oss-cloud auth consumer",
        "rules": ["default.rules"],
        "cmd": [
            "bash",
            fixture_literal("@CODEX_SOURCE@/scripts/run-auth-backed.sh"),
            "--env-file",
            fixture_literal("@HOME@/.codex/.env"),
            "--require-env",
            "OLLAMA_API_KEY",
            "--",
            "bash",
            fixture_literal("@CODEX_SOURCE@/scripts/run-codex-exec.sh"),
            "--profile",
            "oss-cloud",
            "--strict-config",
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--version",
        ],
        "expected_decision": None,
    },
    {
        "name": "default does not bypass policy for Skills SDK oss-cloud consumer",
        "rules": ["default.rules"],
        "cmd": [
            "bash",
            fixture_literal("@CODEX_SOURCE@/scripts/run-auth-backed.sh"),
            "--env-file",
            fixture_literal("@HOME@/.codex/.env"),
            "--require-env",
            "OLLAMA_API_KEY",
            "--",
            "bash",
            fixture_literal("@CODEX_SOURCE@/scripts/run-codex-exec.sh"),
            "--profile",
            "oss-cloud",
            "--strict-config",
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--cd",
            ".",
            "--json",
            "--output-last-message",
            ".harness/artifacts/sdk-ab-evals/example/last-message.json",
            "-",
        ],
        "expected_decision": None,
    },
    {
        "name": "default does not allow arbitrary auth-backed commands",
        "rules": ["default.rules"],
        "cmd": [
            "bash",
            fixture_literal("@CODEX_SOURCE@/scripts/run-auth-backed.sh"),
            "--env-file",
            fixture_literal("@HOME@/.codex/.env"),
            "--require-env",
            "OLLAMA_API_KEY",
            "--",
            "bash",
            "-c",
            "env",
        ],
        "expected_decision": None,
    },
    {
        "name": "guard prompts for npx",
        "rules": ["guard.rules"],
        "cmd": ["npx", "create-next-app@latest"],
        "expected_decision": "prompt",
        "justification_contains": "Ephemeral package executors",
    },
    {
        "name": "guard prompts for uvx",
        "rules": ["guard.rules"],
        "cmd": ["uvx", "ruff", "--version"],
        "expected_decision": "prompt",
        "justification_contains": "Ephemeral package executors",
    },
    {
        "name": "guard prompts for pnpm dlx",
        "rules": ["guard.rules"],
        "cmd": ["pnpm", "dlx", "create-vite"],
        "expected_decision": "prompt",
        "justification_contains": "Package runner commands",
    },
    {
        "name": "guard prompts for curl",
        "rules": ["guard.rules"],
        "cmd": ["curl", "-I", "https://example.com"],
        "expected_decision": "prompt",
        "justification_contains": "Network fetch",
    },
    {
        "name": "guard prompts for scp",
        "rules": ["guard.rules"],
        "cmd": ["scp", "local.txt", "example.com:/tmp/local.txt"],
        "expected_decision": "prompt",
        "justification_contains": "Remote access/transfer",
    },
    {
        "name": "guard prompts for printenv",
        "rules": ["guard.rules"],
        "cmd": ["printenv"],
        "expected_decision": "prompt",
        "justification_contains": "May expose secrets",
    },
    {
        "name": "guard does not re-prompt ordinary topic-branch push",
        "rules": ["guard.rules"],
        "cmd": ["git", "push", "origin", "codex/topic-branch"],
        "expected_decision": None,
    },
    {
        "name": "guard does not re-prompt ordinary commit",
        "rules": ["guard.rules"],
        "cmd": ["git", "commit", "-m", "fix"],
        "expected_decision": None,
    },
    {
        "name": "guard prompts protected primary branch push",
        "rules": ["guard.rules"],
        "cmd": ["git", "push", "origin", "main"],
        "expected_decision": "prompt",
        "justification_contains": "protected primary branch",
    },
    {
        "name": "guard prompts protected upstream branch push",
        "rules": ["guard.rules"],
        "cmd": ["git", "push", "upstream", "main"],
        "expected_decision": "prompt",
        "justification_contains": "protected primary branch",
    },
    {
        "name": "guard prompts protected same-name refspec",
        "rules": ["guard.rules"],
        "cmd": ["git", "push", "origin", "main:main"],
        "expected_decision": "prompt",
        "justification_contains": "protected primary branch",
    },
    {
        "name": "guard prompts fully qualified HEAD protected refspec",
        "rules": ["guard.rules"],
        "cmd": ["git", "push", "origin", "HEAD:refs/heads/main"],
        "expected_decision": "prompt",
        "justification_contains": "protected primary branch",
    },
    {
        "name": "guard prompts force-with-lease push",
        "rules": ["guard.rules"],
        "cmd": ["git", "push", "--force-with-lease", "origin", "codex/topic-branch"],
        "expected_decision": "prompt",
        "justification_contains": "force-with-lease",
    },
    {
        "name": "guard prompts attached force-with-lease ref",
        "rules": ["guard.rules"],
        "cmd": [
            "git",
            "push",
            "--force-with-lease=refs/heads/topic",
            "origin",
            "codex/topic-branch",
        ],
        "expected_decision": "prompt",
        "justification_contains": "force-with-lease",
    },
    {
        "name": "guard prompts force-with-lease expected value",
        "rules": ["guard.rules"],
        "cmd": [
            "git",
            "push",
            f"--force-with-lease=refs/heads/topic:{REAL_LEASE_OID}",
            "origin",
            "codex/topic-branch",
        ],
        "expected_decision": "prompt",
        "justification_contains": "force-with-lease",
    },
    {
        "name": "guard prompts force-with-lease after refspec",
        "rules": ["guard.rules"],
        "cmd": ["git", "push", "origin", "codex/topic-branch", "--force-with-lease"],
        "expected_decision": "prompt",
        "justification_contains": "force-with-lease",
    },
    {
        "name": "guard prompts attached force-with-lease after refspec",
        "rules": ["guard.rules"],
        "cmd": [
            "git",
            "push",
            "origin",
            "codex/topic-branch",
            f"--force-with-lease=refs/heads/topic:{REAL_LEASE_OID}",
        ],
        "expected_decision": "prompt",
        "justification_contains": "force-with-lease",
    },
    {
        "name": "guard prompts hard force before remote",
        "rules": ["guard.rules"],
        "cmd": ["git", "push", "-f", "origin", "HEAD"],
        "expected_decision": "prompt",
        "justification_contains": "force-pushing history",
    },
    {
        "name": "guard prompts hard force after refspec",
        "rules": ["guard.rules"],
        "cmd": ["git", "push", "origin", "HEAD", "--force"],
        "expected_decision": "prompt",
        "justification_contains": "force-pushing history",
    },
    {
        "name": "guard prompts upstream protected destination refspec",
        "rules": ["guard.rules"],
        "cmd": ["git", "push", "upstream", "feature:main"],
        "expected_decision": "prompt",
        "justification_contains": "protected primary branch",
    },
    {
        "name": "guard prompts origin fully qualified protected destination",
        "rules": ["guard.rules"],
        "cmd": ["git", "push", "origin", "feature:refs/heads/main"],
        "expected_decision": "prompt",
        "justification_contains": "protected primary branch",
    },
    {
        "name": "guard prompts reordered amend",
        "rules": ["guard.rules"],
        "cmd": ["git", "commit", "--no-edit", "--amend"],
        "expected_decision": "prompt",
        "justification_contains": "rewriting a commit",
    },
    {
        "name": "guard prompts message before amend",
        "rules": ["guard.rules"],
        "cmd": ["git", "commit", "-m", "fix", "--amend"],
        "expected_decision": "prompt",
        "justification_contains": "rewriting a commit",
    },
    {
        "name": "guard prompts all before amend message",
        "rules": ["guard.rules"],
        "cmd": ["git", "commit", "-a", "--amend", "-m", "fix"],
        "expected_decision": "prompt",
        "justification_contains": "rewriting a commit",
    },
    {
        "name": "guard prompts long all before amend message",
        "rules": ["guard.rules"],
        "cmd": ["git", "commit", "--all", "--amend", "-m", "fix"],
        "expected_decision": "prompt",
        "justification_contains": "rewriting a commit",
    },
    {
        "name": "guard prompts protected branch delete option",
        "rules": ["guard.rules"],
        "cmd": ["git", "push", "origin", "--delete", "main"],
        "expected_decision": "prompt",
        "justification_contains": "protected primary branch",
    },
    {
        "name": "guard prompts protected branch delete refspec",
        "rules": ["guard.rules"],
        "cmd": ["git", "push", "origin", ":main"],
        "expected_decision": "prompt",
        "justification_contains": "protected primary branch",
    },
    {
        "name": "guard prompts multi-ref all push",
        "rules": ["guard.rules"],
        "cmd": ["git", "push", "--all", "origin"],
        "expected_decision": "prompt",
        "justification_contains": "publishing multiple refs",
    },
    {
        "name": "guard forbids remote mirror push",
        "rules": ["guard.rules"],
        "cmd": ["git", "push", "origin", "--mirror"],
        "expected_decision": "forbidden",
        "justification_contains": "Mirrored pushes",
    },
    {
        "name": "guard prompts fully qualified protected refspec",
        "rules": ["guard.rules"],
        "cmd": ["git", "push", "origin", "refs/heads/topic:refs/heads/main"],
        "expected_decision": "prompt",
        "justification_contains": "protected primary branch",
    },
    {
        "name": "guard prompts for git clean",
        "rules": ["guard.rules"],
        "cmd": ["git", "clean", "-fdx"],
        "expected_decision": "prompt",
        "justification_contains": "git clean permanently deletes",
    },
    {
        "name": "guard forbids git commit --no-verify",
        "rules": ["guard.rules"],
        "cmd": ["git", "commit", "--no-verify", "-m", "test"],
        "expected_decision": "forbidden",
        "justification_contains": "Bypassing git hooks is forbidden",
    },
    {
        "name": "guard forbids git push --no-verify",
        "rules": ["guard.rules"],
        "cmd": ["git", "push", "--no-verify", "origin", "HEAD"],
        "expected_decision": "forbidden",
        "justification_contains": "Bypassing git hooks is forbidden",
    },
    {
        "name": "guard forbids sudo rm rf",
        "rules": ["guard.rules"],
        "cmd": ["sudo", "rm", "-rf", "/tmp/example"],
        "expected_decision": "forbidden",
        "justification_contains": "Bypassing privilege and destructive-operation guardrails",
    },
    {
        "name": "guard forbids rm rf root",
        "rules": ["guard.rules"],
        "cmd": ["rm", "-rf", "/"],
        "expected_decision": "forbidden",
        "justification_contains": "never delete root filesystem",
    },
    {
        "name": "project forbids scoped rm -rf",
        "rules": ["project.rules"],
        "cmd": ["rm", "-rf", "./dist"],
        "expected_decision": "forbidden",
    },
    {
        "name": "project forbids git reset hard",
        "rules": ["project.rules"],
        "cmd": ["git", "reset", "--hard", "HEAD"],
        "expected_decision": "forbidden",
    },
    {
        "name": "project forbids git push force",
        "rules": ["project.rules"],
        "cmd": ["git", "push", "--force", "origin", "HEAD"],
        "expected_decision": "forbidden",
    },
    {
        "name": "combined foundation and guard prompt for env",
        "rules": ["foundation.rules", "guard.rules"],
        "cmd": ["env"],
        "expected_decision": "prompt",
        "justification_contains": "May expose secrets",
    },
    {
        "name": "combined foundation and guard prompt for cat env",
        "rules": ["foundation.rules", "guard.rules"],
        "cmd": ["cat", ".env"],
        "expected_decision": "prompt",
        "justification_contains": "May expose secrets",
    },
    {
        "name": "combined project blocks scoped rm rf",
        "rules": ["guard.rules", "project.rules"],
        "cmd": ["rm", "-rf", "./dist"],
        "expected_decision": "forbidden",
        "justification_contains": "Forced recursive deletes",
    },
    {
        "name": "combined force with lease still prompts",
        "rules": ["guard.rules", "project.rules"],
        "cmd": ["git", "push", "--force-with-lease"],
        "expected_decision": "prompt",
        "justification_contains": "force-with-lease",
    },
    {
        "name": "pr diff is read-only",
        "rules": ["pr.rules"],
        "cmd": ["gh", "pr", "diff", "123"],
        "expected_decision": "allow",
    },
    {
        "name": "pr review is prompted",
        "rules": ["pr.rules"],
        "cmd": ["gh", "pr", "review", "123", "--approve"],
        "expected_decision": "prompt",
    },
    {
        "name": "automation leaves canonical environment read approval-governed",
        "rules": ["automation.rules"],
        "cmd": ["cat", fixture_literal("@CODEX_SOURCE@/environments/environment.toml")],
        "expected_decision": None,
    },
    {
        "name": "automation allows merged branch inspection",
        "rules": ["automation.rules"],
        "cmd": ["git", "branch", "--merged"],
        "expected_decision": "allow",
    },
    {
        "name": "automation forbids primary branch deletion",
        "rules": ["automation.rules"],
        "cmd": ["git", "branch", "-d", "main"],
        "expected_decision": "forbidden",
    },
    {
        "name": "automation prompts local branch prune",
        "rules": ["automation.rules"],
        "cmd": ["git", "branch", "-d", "feature/already-merged"],
        "expected_decision": "prompt",
        "justification_contains": "cannot prove",
    },
]
CASES.extend(
    [
        {
            "name": "guard prompts full dependency lock upgrade",
            "rules": ["guard.rules"],
            "cmd": ["uv", "lock", "--upgrade"],
            "expected_decision": "prompt",
            "justification_contains": "resolved dependencies",
        },
        {
            "name": "guard prompts abbreviated dependency lock upgrade",
            "rules": ["guard.rules"],
            "cmd": ["uv", "lock", "-U"],
            "expected_decision": "prompt",
            "justification_contains": "resolved dependencies",
        },
        {
            "name": "guard prompts package-specific dependency lock upgrade",
            "rules": ["guard.rules"],
            "cmd": ["uv", "lock", "--upgrade-package", "pydantic"],
            "expected_decision": "prompt",
            "justification_contains": "resolved dependencies",
        },
        {
            "name": "guard leaves non-upgrade dependency lock approval-governed",
            "rules": ["guard.rules"],
            "cmd": ["uv", "lock", "--check"],
            "expected_decision": None,
        },
        {
            "name": "guard prompts broad short-form staging",
            "rules": ["guard.rules"],
            "cmd": ["git", "add", "-A"],
            "expected_decision": "prompt",
            "justification_contains": "unrelated or sensitive files",
        },
        {
            "name": "guard prompts broad long-form staging",
            "rules": ["guard.rules"],
            "cmd": ["git", "add", "--all"],
            "expected_decision": "prompt",
            "justification_contains": "unrelated or sensitive files",
        },
        {
            "name": "guard leaves path-scoped staging approval-governed",
            "rules": ["guard.rules"],
            "cmd": ["git", "add", "--", "src/app.py"],
            "expected_decision": None,
        },
        {
            "name": "effective rules leave routine native commit approval-governed",
            "rules": [EFFECTIVE_RULES_SENTINEL],
            "cmd": ["git", "commit", "-m", "test"],
            "expected_decision": None,
        },
        {
            "name": "effective rules do not re-prompt historical shell-wrapped push",
            "rules": [EFFECTIVE_RULES_SENTINEL],
            "cmd": [
                "zsh",
                "-lc",
                fixture_literal("cd @HOME@/dev/agent-skills && git push"),
            ],
            "expected_decision": None,
        },
        {
            "name": "effective rules do not re-prompt historical direct branch push",
            "rules": [EFFECTIVE_RULES_SENTINEL],
            "cmd": [
                "zsh",
                "-lc",
                "git push origin codex/environment-only-prepush-gate",
            ],
            "expected_decision": None,
        },
        {
            "name": "effective rules do not allow historical shell-wrapped commit",
            "rules": [EFFECTIVE_RULES_SENTINEL],
            "cmd": [
                "zsh",
                "-lc",
                fixture_literal(
                    "cd @HOME@/dev/coding-harness && git commit -m 'historical direct commit'"
                ),
            ],
            "expected_decision": None,
        },
        {
            "name": "effective rules do not allow historical amend",
            "rules": [EFFECTIVE_RULES_SENTINEL],
            "cmd": [
                "zsh",
                "-lc",
                "git commit --amend --no-edit; code=$?; echo AMEND_EXIT:$code; exit $code",
            ],
            "expected_decision": None,
        },
        {
            "name": "effective rules forbid direct no-verify commit",
            "rules": [EFFECTIVE_RULES_SENTINEL],
            "cmd": ["git", "commit", "--no-verify", "-m", "test"],
            "expected_decision": "forbidden",
            "justification_contains": "Bypassing git hooks",
        },
        {
            "name": "effective rules prompt PR creation",
            "rules": [EFFECTIVE_RULES_SENTINEL],
            "cmd": ["gh", "pr", "create", "--body-file", "/tmp/pr-body.md"],
            "expected_decision": "prompt",
            "justification_contains": "PR creation",
        },
        {
            "name": "effective rules allow issue view",
            "rules": [EFFECTIVE_RULES_SENTINEL],
            "cmd": ["gh", "issue", "view", "123"],
            "expected_decision": "allow",
            "justification_contains": "read-only GitHub issue",
        },
        {
            "name": "effective rules allow run watch",
            "rules": [EFFECTIVE_RULES_SENTINEL],
            "cmd": ["gh", "run", "watch", "123"],
            "expected_decision": "allow",
            "justification_contains": "read-only GitHub Actions",
        },
        {
            "name": "effective rules allow workflow view",
            "rules": [EFFECTIVE_RULES_SENTINEL],
            "cmd": ["gh", "workflow", "view", "ci.yml"],
            "expected_decision": "allow",
            "justification_contains": "read-only GitHub workflow",
        },
        {
            "name": "effective rules allow release list",
            "rules": [EFFECTIVE_RULES_SENTINEL],
            "cmd": ["gh", "release", "list"],
            "expected_decision": "allow",
            "justification_contains": "read-only GitHub release",
        },
        {
            "name": "effective rules prompt issue comment",
            "rules": [EFFECTIVE_RULES_SENTINEL],
            "cmd": ["gh", "issue", "comment", "123", "--body-file", "/tmp/comment.md"],
            "expected_decision": "prompt",
            "justification_contains": "issue remote mutations",
        },
        {
            "name": "effective rules prompt release creation",
            "rules": [EFFECTIVE_RULES_SENTINEL],
            "cmd": ["gh", "release", "create", "v1.2.3"],
            "expected_decision": "prompt",
            "justification_contains": "release remote mutations",
        },
        {
            "name": "effective rules prompt workflow dispatch",
            "rules": [EFFECTIVE_RULES_SENTINEL],
            "cmd": ["gh", "workflow", "run", "ci.yml"],
            "expected_decision": "prompt",
            "justification_contains": "workflow dispatch",
        },
        {
            "name": "effective rules prompt repository settings mutation",
            "rules": [EFFECTIVE_RULES_SENTINEL],
            "cmd": ["gh", "repo", "edit", "owner/repo"],
            "expected_decision": "prompt",
            "justification_contains": "repository settings",
        },
        {
            "name": "effective rules prompt raw GitHub API write",
            "rules": [EFFECTIVE_RULES_SENTINEL],
            "cmd": ["gh", "api", "-X", "POST", "/repos/owner/repo/issues"],
            "expected_decision": "prompt",
            "justification_contains": "gh api write operations",
        },
        {
            "name": "effective rules prompt raw GitHub GraphQL mutation",
            "rules": [EFFECTIVE_RULES_SENTINEL],
            "cmd": [
                "gh",
                "api",
                "graphql",
                "-f",
                "query=mutation($threadId:ID!){resolveReviewThread(input:{threadId:$threadId}){thread{id isResolved}}}",
                "-F",
                "threadId=PRRT_example",
            ],
            "expected_decision": "prompt",
            "justification_contains": "Raw GitHub GraphQL",
        },
        {
            "name": "effective rules forbid mirror push collision",
            "rules": [EFFECTIVE_RULES_SENTINEL],
            "cmd": ["git", "push", "origin", "--mirror"],
            "expected_decision": "forbidden",
            "justification_contains": "Mirrored pushes",
        },
    ]
)


def effective_rule_paths() -> list[Path]:
    """Return the complete canonical runtime rule set."""
    return sorted(RULES_DIR.glob("*.rules"), key=lambda path: path.name)


def validate_rule_aliases() -> tuple[bool, str]:
    """Reject compatibility aliases and duplicate rule targets."""
    aliases: dict[str, str] = {}
    canonical_owners: dict[Path, list[str]] = {}
    for path in effective_rule_paths():
        resolved = path.resolve()
        canonical_owners.setdefault(resolved, []).append(path.name)
        if path.is_symlink():
            if resolved.parent != RULES_DIR.resolve():
                return (
                    False,
                    f"rule alias {path.name} resolves outside {RULES_DIR}: {resolved}",
                )
            aliases[path.name] = resolved.name
    if aliases:
        return (False, f"rule aliases are retired; use canonical files: {aliases}")
    unexpected_duplicates = {
        str(target): names
        for target, names in canonical_owners.items()
        if len(names) > 1
    }
    if unexpected_duplicates:
        return (
            False,
            f"unexpected duplicate canonical rule targets: {unexpected_duplicates}",
        )
    return (True, f"PASS canonical rules ({len(effective_rule_paths())} loaded paths)")


def validate_default_rule_hygiene() -> tuple[bool, str]:
    """Keep the default layer limited to the two durable auth canaries."""
    policy = (RULES_DIR / "default.rules").read_text(encoding="utf-8")
    expected_canaries = ("OLLAMA_API_KEY", "CIRCLECI_CLI_TOKEN")
    if policy.count("prefix_rule(") != len(expected_canaries):
        return (
            False,
            "default.rules must contain exactly the two durable auth canaries",
        )
    if any(policy.count(canary) != 3 for canary in expected_canaries):
        return (False, "default.rules auth canary patterns or examples are incomplete")
    decisions = [
        value
        for _, value in re.findall(
            "\\bdecision\\s*=\\s*(['\\\"])([^'\\\"]+)\\1", policy
        )
    ]
    if decisions != ["allow", "allow"]:
        return (False, "default.rules must contain exactly two allow decisions")
    return (True, "PASS default.rules durable exception boundary (2 auth canaries)")


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(value, minimum)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


EXEC_TIMEOUT_SEC = _env_int("CODEX_EXECPOLICY_TIMEOUT_SEC", 12)
EXEC_RETRIES = _env_int("CODEX_EXECPOLICY_RETRIES", 1, minimum=0)
REQUIRE_EXECPOLICY_CLI = True  # Missing native CLI cannot clear this fixture lane.


def resolve_codex_bin() -> str:
    override = os.getenv("CODEX_BIN")
    if override:
        return override
    try:
        result = subprocess.run(
            ["mise", "which", "codex"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        result = None
    if result and result.returncode == 0:
        candidate = result.stdout.strip().splitlines()[-1]
        if candidate:
            return candidate
    return shutil.which("codex") or "codex"


def load_requirements_toml() -> dict[str, object]:
    raw_text = REQUIREMENTS_PATH.read_text()
    if tomllib is not None:
        return tomllib.loads(raw_text)
    data: dict[str, object] = {}
    current_identity: dict[str, str] | None = None
    for raw_line in raw_text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line.strip("[]")
            parts = section.split(".")
            if (
                len(parts) == 3
                and parts[0] == "mcp_servers"
                and (parts[2] == "identity")
            ):
                servers = data.setdefault("mcp_servers", {})
                if not isinstance(servers, dict):
                    raise ValueError("mcp_servers must be a table")
                server = servers.setdefault(parts[1], {})
                if not isinstance(server, dict):
                    raise ValueError(f"mcp_servers.{parts[1]} must be a table")
                current_identity = server.setdefault("identity", {})
                if not isinstance(current_identity, dict):
                    raise ValueError(f"mcp_servers.{parts[1]}.identity must be a table")
                continue
            raise ValueError(f"unsupported TOML section: {section}")
        if "=" not in line:
            raise ValueError(f"unsupported TOML line: {raw_line}")
        key, value = [part.strip() for part in line.split("=", 1)]
        if current_identity is not None:
            current_identity[key] = json.loads(value)
        elif key in {"allowed_approval_policies", "allowed_sandbox_modes"}:
            data[key] = json.loads(value)
        else:
            raise ValueError(f"unsupported TOML key: {key}")
    return data


def run_execpolicy_command(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(
        prefix="dots-execpolicy-", dir=require_fixture_path(Path(os.environ["TMPDIR"]))
    ) as codex_home:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=REPO_ROOT,
            env={**os.environ, "CODEX_HOME": codex_home},
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=EXEC_TIMEOUT_SEC)
        except subprocess.TimeoutExpired as exc:
            os.killpg(process.pid, signal.SIGKILL)
            try:
                stdout, stderr = process.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                stdout = exc.output or ""
                stderr = exc.stderr or ""
            raise subprocess.TimeoutExpired(
                exc.cmd, exc.timeout, output=stdout, stderr=stderr
            ) from exc
        return subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)


def run_case(case: dict, codex_bin: str) -> tuple[bool, str]:
    cmd = [codex_bin, "execpolicy", "check", "--pretty"]
    for rule_file in case["rules"]:
        if rule_file == EFFECTIVE_RULES_SENTINEL:
            for rule_path in effective_rule_paths():
                cmd.extend(["--rules", str(rule_path)])
        else:
            cmd.extend(["--rules", str(RULES_DIR / rule_file)])
    cmd.append("--")
    cmd.extend(case["cmd"])
    last_error = ""
    result = None
    payload: dict[str, object] | None = None
    for attempt in range(1, EXEC_RETRIES + 2):
        try:
            result = run_execpolicy_command(cmd)
        except subprocess.TimeoutExpired:
            last_error = f"{case['name']}: execpolicy check timed out after {EXEC_TIMEOUT_SEC}s (attempt {attempt}/{EXEC_RETRIES + 1})"
            continue
        if result.returncode != 0:
            last_error = f"{case['name']}: exec failed with code {result.returncode} (attempt {attempt}/{EXEC_RETRIES + 1})\n{result.stderr}"
            continue
        try:
            payload = json.loads(result.stdout)
            break
        except json.JSONDecodeError as exc:
            last_error = f"{case['name']}: invalid JSON output on attempt {attempt}/{EXEC_RETRIES + 1}: {exc}\n{result.stdout}"
    if payload is None or result is None:
        return (False, last_error)
    decision = payload.get("decision")
    expected = case["expected_decision"]
    if decision != expected:
        return (
            False,
            f"{case['name']}: expected decision {expected!r}, got {decision!r}\n{result.stdout}",
        )
    justification_contains = case.get("justification_contains")
    if justification_contains:
        matched_rules = payload.get("matchedRules", [])
        if not isinstance(matched_rules, list):
            return (False, f"{case['name']}: matchedRules must be an array")
        justifications = [
            rule.get("prefixRuleMatch", {}).get("justification", "")
            for rule in matched_rules
            if isinstance(rule, dict) and isinstance(rule.get("prefixRuleMatch"), dict)
        ]
        if not any(justification_contains in text for text in justifications):
            return (
                False,
                f"{case['name']}: missing justification substring {justification_contains!r}\n{result.stdout}",
            )
    return (True, f"PASS {case['name']}")


def execpolicy_cli_available(codex_bin: str) -> tuple[bool, str]:
    """Probe command availability without evaluating any policy assertion."""
    try:
        result = run_execpolicy_command([codex_bin, "execpolicy", "check", "--help"])
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return (
            False,
            f"SKIP execpolicy CLI-backed cases: capability probe unavailable: {exc}",
        )
    except OSError as exc:
        return (False, f"execpolicy capability probe failed: {exc}")
    if result.returncode != 0:
        return (False, f"execpolicy capability probe failed: {result.stderr}")
    return (True, "PASS execpolicy CLI capability probe")


def validate_requirements() -> tuple[bool, str]:
    try:
        data = load_requirements_toml()
    except (OSError, ValueError) as exc:
        return (False, f"requirements.toml failed to parse: {exc}")
    unexpected = set(data) - {
        "allowed_approval_policies",
        "allowed_sandbox_modes",
        "mcp_servers",
    }
    if unexpected:
        return (False, f"requirements.toml has unsupported keys: {sorted(unexpected)}")
    approval_policies = data.get("allowed_approval_policies")
    if not isinstance(approval_policies, list) or not approval_policies:
        return (False, "requirements.toml must define allowed_approval_policies")
    if any(
        policy not in {"untrusted", "on-request", "never"}
        for policy in approval_policies
    ):
        return (
            False,
            "requirements.toml allowed_approval_policies contains an unsupported policy",
        )
    sandbox_modes = data.get("allowed_sandbox_modes")
    if not isinstance(sandbox_modes, list) or "read-only" not in sandbox_modes:
        return (False, "requirements.toml allowed_sandbox_modes must include read-only")
    allowed_sandbox_modes = {
        "read-only",
        "workspace-write",
        "danger-full-access",
        "external-sandbox",
    }
    if any(mode not in allowed_sandbox_modes for mode in sandbox_modes):
        return (
            False,
            "requirements.toml allowed_sandbox_modes contains an unsupported mode",
        )
    mcp_servers = data.get("mcp_servers")
    if not isinstance(mcp_servers, dict) or not mcp_servers:
        return (
            False,
            "requirements.toml must define one or more mcp_servers identities",
        )
    for name, server in sorted(mcp_servers.items()):
        if not isinstance(server, dict):
            return (False, f"requirements.toml mcp_servers.{name} must be a table")
        identity = server.get("identity")
        if not isinstance(identity, dict):
            return (
                False,
                f"requirements.toml mcp_servers.{name}.identity must be a table",
            )
        has_command = isinstance(identity.get("command"), str) and bool(
            identity.get("command", "").strip()
        )
        has_url = isinstance(identity.get("url"), str) and bool(
            identity.get("url", "").strip()
        )
        if has_command == has_url:
            return (
                False,
                f"requirements.toml mcp_servers.{name}.identity must set exactly one of command or url",
            )
    return (True, f"PASS requirements.toml ({len(mcp_servers)} MCP identities)")


def validate_fixture_boundary() -> tuple[bool, str]:
    """Bind managed constraints to canonical input; never install system policy."""
    try:
        require_disposable_scope()
        require_fixture_path(Path(os.environ["TMPDIR"]))
        expected_names = {
            "automation.rules",
            "default.rules",
            "foundation.rules",
            "guard.rules",
            "pr.rules",
            "project.rules",
            "workflow-guardrails.md",
        }
        if {path.name for path in RULES_DIR.iterdir()} != expected_names:
            raise ValueError("Canonical rule inventory changed")
        for path in (
            REQUIREMENTS_PATH,
            REPO_ROOT / "config.toml",
            *RULES_DIR.iterdir(),
        ):
            require_fixture_path(path)
            if not path.is_file() or path.is_symlink() or path.stat().st_nlink != 1:
                raise ValueError(
                    "Canonical controls must be separate regular fixture files"
                )
        data = load_requirements_toml()
        policy = tomllib.loads((REPO_ROOT / "config.toml").read_text())
        identities = {
            name: {"identity": {"url": policy["mcp_servers"][name]["url"]}}
            for name in ("openaiDeveloperDocs", "codex-repo")
        }
        if data != {
            "allowed_approval_policies": ["on-request", "never"],
            "allowed_sandbox_modes": ["read-only", "workspace-write"],
            "mcp_servers": identities,
        }:
            raise ValueError(
                "Managed constraints disagree with the accepted baseline or canonical identities"
            )
    except (KeyError, OSError, TypeError, ValueError, RuntimeError) as exc:
        return False, f"Fixture controls boundary failed: {exc}"
    return True, "PASS fixture-only controls and exact canonical MCP identities"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--static-only",
        action="store_true",
        help="Check fixture constraints and rule hygiene without claiming native match coverage",
    )
    arguments = parser.parse_args()
    messages: list[str] = []
    failures: list[str] = []
    ok, message = validate_fixture_boundary()
    if not ok:
        print(message, file=sys.stderr)
        return 1
    messages.append(message)
    ok, message = validate_requirements()
    (messages if ok else failures).append(message)
    ok, message = validate_rule_aliases()
    (messages if ok else failures).append(message)
    ok, message = validate_default_rule_hygiene()
    (messages if ok else failures).append(message)
    if arguments.static_only:
        for message in messages:
            print(message)
        for message in failures:
            print(message, file=sys.stderr)
        print("Static controls only; native execpolicy cases were not run.")
        return 1 if failures else 0
    codex_bin = resolve_codex_bin()
    cli_available, message = execpolicy_cli_available(codex_bin)
    if cli_available:
        messages.append(message)
        for case in CASES:
            ok, message = run_case(case, codex_bin)
            (messages if ok else failures).append(message)
    else:
        optional_unavailable = message.startswith(
            "SKIP execpolicy CLI-backed cases:"
        ) and (not REQUIRE_EXECPOLICY_CLI)
        (messages if optional_unavailable else failures).append(message)
    for message in messages:
        print(message)
    if failures:
        for message in failures:
            print(message, file=sys.stderr)
        return 1
    validated_cases = len(CASES) if cli_available else 0
    print(
        f"Validated {validated_cases} execpolicy cases plus current requirements.toml baseline."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
