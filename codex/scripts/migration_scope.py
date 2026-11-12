"""Keep the inactive governance port confined to an explicit disposable HOME."""

import os
import pwd
from pathlib import Path


def require_disposable_scope():
    value = os.environ.get("DOTS_TEST_HOME", "")
    fixture_root = os.environ.get("DOTS_FIXTURE_ROOT", "")
    if fixture_root:
        root = Path(fixture_root)
        current_home = Path(os.environ.get("HOME", ""))
        account_home = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
        temporary = Path("/tmp").resolve()
        if (
            not root.is_absolute()
            or root == temporary
            or not root.is_relative_to(temporary)
            or root != root.resolve()
            or not root.is_dir()
            or value != str(root)
            or root.is_relative_to(account_home)
            or ".." in root.parts
            or not current_home.is_absolute()
            or not current_home.is_dir()
            or current_home != current_home.resolve()
            or ".." in current_home.parts
            or not current_home.is_relative_to(root)
        ):
            raise RuntimeError(
                "Nested helper HOME must remain inside its explicit disposable fixture root"
            )
        path, resource_root = current_home, root
    else:
        path = Path(value)
        roots = (Path("/tmp").resolve(),)
        account_home = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
        if (
            not value
            or not path.is_absolute()
            or ".." in path.parts
            or not path.is_dir()
            or path != path.resolve()
            or not any(path != root and path.is_relative_to(root) for root in roots)
            or os.environ.get("HOME") != str(path)
            or path.is_relative_to(account_home)
        ):
            raise RuntimeError(
                "An explicit disposable DOTS_TEST_HOME matching HOME is required"
            )
        resource_root = path
    for name in (
        "CODEX_CONFIG_SOURCE_ROOT",
        "CODEX_SOURCE_SCHEMA_PATH",
        "CODEX_UNIFIED_COMPUTER_USE_PLUGIN_ROOT",
        "CODEX_UNIFIED_COMPUTER_USE_NODE_PATH",
        "CODEX_UNIFIED_COMPUTER_USE_NODE_REPL_PATH",
        "CODEX_PROJECT_CONFIG_SEARCH_ROOTS",
    ):
        values = os.environ.get(name, "")
        for item in values.split(os.pathsep) if values else ():
            candidate = Path(item)
            if (
                not candidate.is_absolute()
                or ".." in candidate.parts
                or not candidate.resolve().is_relative_to(resource_root)
            ):
                raise RuntimeError(
                    "Validation resource override leaves disposable home"
                )
    return path


def local_path_text(value):
    home = require_policy_scope()
    result = value.replace("@HOME@", str(home))
    module = deployment_module()
    if module is not None:
        if value == '@HOME@/.local/share/codex-storage/sessions':
            return module.context()['session_evidence_root']
        result = result.replace(str(home / 'dev/dots/codex/usage-data'),
                                str(home / '.codex/usage-data'))
        result = result.replace(str(home / 'dev/dots'), str(module.ROOT))
    return result


def require_fixture_path(path):
    home = require_disposable_scope()
    if os.environ.get("DOTS_FIXTURE_ROOT"):
        home = Path(os.environ["DOTS_FIXTURE_ROOT"])
    path = Path(path).absolute()
    if (
        ".." in path.parts
        or not path.is_relative_to(home)
        or not path.resolve().is_relative_to(home)
    ):
        raise ValueError("Path must remain within the disposable home")
    return path


def require_auth_free_environment():
    """Withhold supported provider credentials and bound authentication stores."""
    require_disposable_scope()
    for name in (
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "GH_ENTERPRISE_TOKEN",
        "GITHUB_ENTERPRISE_TOKEN",
        "OPENAI_API_KEY",
        "OP_SERVICE_ACCOUNT_TOKEN",
    ):
        if os.environ.get(name):
            raise RuntimeError("Real provider credentials are not admitted in fixtures")
    for name in ("GH_CONFIG_DIR", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        if os.environ.get(name):
            require_fixture_path(Path(os.environ[name]).expanduser())
    # GitHub CLI also reads its default store when neither override is set.
    # Admit every leaf without reading credentials, following only in-root
    # directory aliases so a second symlink cannot escape behind the first.
    configured = os.environ.get("GH_CONFIG_DIR")
    if configured:
        store = Path(configured).expanduser()
    elif os.environ.get("XDG_CONFIG_HOME"):
        store = Path(os.environ["XDG_CONFIG_HOME"]).expanduser() / "gh"
    else:
        store = Path(os.environ["HOME"]) / ".config" / "gh"
    pending, seen = [store], set()
    while pending:
        candidate = require_fixture_path(pending.pop()).resolve()
        if candidate.is_dir() and candidate not in seen:
            seen.add(candidate)
            pending.extend(candidate.iterdir())


_DEPLOYMENT_MODULE = None


def deployment_module():
    """Load only the packaged sibling; no environment flag selects deployment."""
    import importlib.util
    global _DEPLOYMENT_MODULE
    marker = Path(__file__).resolve().parents[1] / '.deployment.json'
    if not os.path.lexists(marker):
        return None
    if _DEPLOYMENT_MODULE is not None:
        return _DEPLOYMENT_MODULE
    spec = importlib.util.spec_from_file_location('dots_deployment_scope',
        Path(__file__).with_name('deployment_scope.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _DEPLOYMENT_MODULE = module
    return module


def require_policy_scope():
    module = deployment_module()
    if module is None:
        return require_disposable_scope()
    return Path(module.context()['home'])


def require_policy_path(path):
    module = deployment_module()
    return require_fixture_path(path) if module is None else module.require_path(path)


def require_policy_output(path):
    module = deployment_module()
    return require_fixture_path(path) if module is None else module.require_path(path, output=True)


def require_policy_environment():
    module = deployment_module()
    return require_auth_free_environment() if module is None else module.require_environment()
