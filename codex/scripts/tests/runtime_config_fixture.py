"""Build a second canonical fixture using public code and generated test policy."""

import json
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

from helper_fixture_scope import admit_file, output, resource


def create_runtime_checkout(repo: Path, source_root: Path) -> None:
    """Keep the accepted snapshot scenario inside a dedicated nested HOME."""
    admit_file(__file__)
    repo, source_root = resource(repo), resource(source_root)
    home = repo.parent.parent
    if repo != home / "dev/dots":
        raise ValueError(
            "Nested canonical fixture must retain the HOME/dev/dots layout"
        )
    repo.mkdir(parents=True)
    tracked = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=source_root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.split("\0")
    # Generated fixture policy is deliberately ignored by the public repository.
    # Include it explicitly without changing the public source allowlist.
    generated = [
        "codex/config.toml",
        "codex/projection-map.json",
        "codex/requirements.toml",
        "codex/hooks/hooks.json",
    ]
    closed_map = json.loads((source_root / "codex/projection-map.json").read_text())
    generated.extend(
        row["source"]
        for row in closed_map["codex_projection"]
        if row.get("source", "").endswith(".toml")
    )
    generated.extend(
        path.relative_to(source_root).as_posix()
        for path in (source_root / "codex/rules").glob("*.rules")
    )
    generated.extend(
        path.relative_to(source_root).as_posix()
        for path in (source_root / "codex/hooks").glob("braid-*/braid")
    )
    for name in sorted(set(filter(None, tracked + generated))):
        source = resource(source_root / name)
        if not source.exists() and not source.is_symlink():
            continue
        target = resource(repo / name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target, follow_symlinks=False)
    subprocess.run(
        ["git", "init", "-q", str(repo)], check=True, timeout=30, capture_output=True
    )
    subprocess.run(
        ["git", "add", "--all"], cwd=repo, check=True, timeout=30, capture_output=True
    )

    codex = repo / "codex"
    source_home = source_root.parent.parent
    if source_root != source_home / "dev/dots":
        raise ValueError(
            "Source canonical fixture must retain the HOME/dev/dots layout"
        )
    original_home = str(source_home)
    bindings = {str(source_root / "codex"): str(codex), original_home: str(home)}
    pattern = re.compile("|".join(re.escape(value) for value in bindings))
    for path in [
        *codex.glob("*.toml"),
        codex / "hooks/hooks.json",
        *codex.glob("rules/*.rules"),
    ]:
        text = resource(path).read_text()
        text = pattern.sub(lambda match: bindings[match[0]], text)
        resource(path).write_text(text)
    config = codex / "config.toml"
    canonical = config.read_text()
    parsed = tomllib.loads(canonical)
    for project_path in parsed.get("projects", {}):
        project = Path(project_path)
        if (
            not project.is_absolute()
            or ".." in project.parts
            or not project.resolve().is_relative_to(home.resolve())
        ):
            raise ValueError("Nested fixture project leaves its disposable HOME")
        output(project).mkdir(parents=True, exist_ok=True)
    for name, marketplace in parsed.get("marketplaces", {}).items():
        registry = repo / "fixture-marketplaces" / name
        registry.mkdir(parents=True)
        entries = [
            {"name": plugin.rsplit("@", 1)[0]}
            for plugin in parsed.get("plugins", {})
            if plugin.endswith("@" + name)
        ]
        (registry / "marketplace.json").write_text(
            json.dumps({"name": name, "plugins": entries})
        )
        canonical = canonical.replace(marketplace["source"], str(registry))
    config.write_text(canonical)
    environment = os.environ | {
        "HOME": str(home),
        "CODEX_HOME": str(home / ".codex"),
        "CODEX_CONFIG_SOURCE_ROOT": str(codex),
        "CODEX_SOURCE_SCHEMA_PATH": str(codex / "schemas/config.schema.json"),
        "CODEX_PROJECT_CONFIG_TARGET": str(config),
        "CODEX_DEV_ROOT": str(repo),
        "CODEX_PROJECT_CONFIG_SEARCH_ROOTS": str(repo),
    }
    result = subprocess.run(
        [
            "bash",
            str(repo / "scripts/link-configs.sh"),
            "--repair",
            "--scope",
            "codex",
            "--codex-home",
            str(home / ".codex"),
        ],
        env=environment,
        cwd=repo,
        text=True,
        capture_output=True,
        timeout=45,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            "Nested runtime fixture projection failed: " + result.stdout + result.stderr
        )
