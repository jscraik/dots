"""Materialize the pinned, complete hook runtime without installing it."""

import argparse
import hashlib
import json
import os
import platform as host_platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path


LOCK = Path(__file__).resolve().parents[1] / "templates/hook-toolchain-lock.json"


def member_path(root, name):
    parts = Path(name).parts
    if Path(name).is_absolute() or ".." in parts:
        raise ValueError("Archive member leaves the payload")
    target = root.joinpath(*parts)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Archive member traverses an external link")
    return target


def extract(archive, root):
    """Extract regular files and internal symlinks, rejecting special entries."""
    with tarfile.open(archive) as stream:
        for item in stream:
            target = member_path(root, item.name)
            if item.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if item.issym():
                link = Path(item.linkname)
                if link.is_absolute() or not (target.parent / link).resolve().is_relative_to(root.resolve()):
                    raise ValueError("Archive symlink leaves the payload")
                target.symlink_to(item.linkname)
            elif item.isfile():
                source = stream.extractfile(item)
                if source is None:
                    raise ValueError("Archive file has no content")
                with source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(0o755 if item.mode & stat.S_IXUSR else 0o644)
            else:
                raise ValueError("Archive contains an unsupported entry")


def build(platform, output):
    native = ("darwin-arm64" if sys.platform == "darwin" and host_platform.machine() == "arm64"
              else "linux-amd64" if sys.platform.startswith("linux") and host_platform.machine() == "x86_64"
              else None)
    if platform != native:
        raise ValueError("Prepare the payload on its native platform")
    lock = json.loads(LOCK.read_text())
    artifacts = lock["platforms"][platform]
    if output.exists() or output.is_symlink():
        raise ValueError("Output must be a new directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as directory:
        staging = Path(directory)
        payload = staging / "payload"
        payload.mkdir()
        (payload / "bin").mkdir()
        for name, artifact in artifacts.items():
            archive = staging / name
            with urllib.request.urlopen(artifact["url"], timeout=60) as response, archive.open("xb") as target:
                shutil.copyfileobj(response, target)
            if hashlib.sha256(archive.read_bytes()).hexdigest() != artifact["sha256"]:
                raise ValueError("Pinned artifact digest mismatch: " + name)
            if name == "jq":
                shutil.copyfile(archive, payload / "bin/jq")
                (payload / "bin/jq").chmod(0o755)
            elif name == "gh" and platform.startswith("darwin"):
                with zipfile.ZipFile(archive) as stream:
                    members = [item for item in stream.infolist() if item.filename.endswith("/bin/gh")]
                    if len(members) != 1:
                        raise ValueError("GitHub CLI archive has ambiguous executables")
                    with stream.open(members[0]) as source, (payload / "bin/gh").open("xb") as target:
                        shutil.copyfileobj(source, target)
                    (payload / "bin/gh").chmod(0o755)
            else:
                extract(archive, payload)
                if name == "gh":
                    matches = list(payload.glob("gh_*/bin/gh"))
                    if len(matches) != 1:
                        raise ValueError("GitHub CLI archive has ambiguous executables")
                    shutil.copyfile(matches[0], payload / "bin/gh")
                    (payload / "bin/gh").chmod(0o755)
        python = payload / "python/bin/python3.12"
        if not python.is_file():
            raise ValueError("Standalone Python payload is incomplete")
        dependency_lock = LOCK.parents[2] / "requirements/hook-toolchain.lock"
        subprocess.run([
            str(python), "-I", "-m", "pip", "--isolated", "install", "--require-hashes",
            "--only-binary=:all:", "--no-cache-dir", "-r", str(dependency_lock),
        ], check=True, timeout=300)
        (payload / "bin/python3").symlink_to("../python/bin/python3.12")
        (payload / "toolchain.json").write_text(json.dumps({
            "version": lock["version"], "platform": platform, "artifacts": artifacts,
        }, indent=2) + "\n")
        os.rename(payload, output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=("darwin-arm64", "linux-amd64"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.platform, args.output.absolute())
