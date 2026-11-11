"""Render public rule and managed-requirements templates without installing them."""

import argparse
import ast
import importlib.util
import shlex
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "control_policy", ROOT / "scripts/generate-codex-policy.py"
)
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)
RULE_NAMES = (
    "automation.rules",
    "default.rules",
    "foundation.rules",
    "guard.rules",
    "pr.rules",
    "project.rules",
)


def render_rule(text: str, source: Path, home: Path) -> str:
    """Replace data constants in the AST, never interpolate executable syntax."""

    def path_value(value: str) -> str:
        return value.replace("@CODEX_SOURCE@", str(source)).replace("@HOME@", str(home))

    class Paths(ast.NodeTransformer):
        def visit_Call(self, node: ast.Call) -> ast.Call:
            if (
                not isinstance(node.func, ast.Name)
                or node.func.id != "prefix_rule"
                or node.args
            ):
                raise ValueError("Only declarative prefix_rule calls are supported")
            for keyword in node.keywords:
                if keyword.arg in {"match", "not_match"}:
                    examples = ast.literal_eval(keyword.value)
                    keyword.value = ast.List(
                        elts=[
                            ast.Constant(
                                shlex.join(
                                    [path_value(part) for part in shlex.split(example)]
                                )
                            )
                            for example in examples
                        ],
                        ctx=ast.Load(),
                    )
                else:
                    keyword.value = self.visit(keyword.value)
            return node

        def visit_Constant(self, node: ast.Constant) -> ast.Constant:
            if isinstance(node.value, str):
                return ast.copy_location(ast.Constant(path_value(node.value)), node)
            return node

    tree = ast.parse(text)
    if any(
        not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call)
        for node in tree.body
    ):
        raise ValueError("Rules must contain only declarative prefix_rule expressions")
    rendered = ast.unparse(ast.fix_missing_locations(Paths().visit(tree))) + "\n"
    ast.parse(rendered)
    return rendered


def render_controls(
    policy: dict, source: Path, home: Path
) -> tuple[dict[str, str], str]:
    """Generate strings only; the caller owns fixture admission and publication."""
    if (
        not source.is_absolute()
        or not home.is_absolute()
        or ".." in (*source.parts, *home.parts)
    ):
        raise ValueError("Explicit absolute, normalised local paths are required")
    rules = {}
    for name in RULE_NAMES:
        template = POLICY.STAGE.read_regular(
            ROOT / "codex/templates/rules" / name
        ).decode()
        rules[name] = render_rule(template, source, home)
    template = POLICY.STAGE.read_regular(
        ROOT / "codex/templates/requirements.toml"
    ).decode()
    requirements = tomllib.loads(template)
    if (
        set(requirements)
        != {"allowed_approval_policies", "allowed_sandbox_modes", "mcp_servers"}
        or requirements["allowed_approval_policies"] != ["on-request", "never"]
        or requirements["allowed_sandbox_modes"] != ["read-only", "workspace-write"]
        or set(requirements["mcp_servers"]) != {"openaiDeveloperDocs", "codex-repo"}
    ):
        raise ValueError(
            "Managed requirements template departed from the accepted baseline"
        )
    servers = requirements["mcp_servers"]
    for name in ("openaiDeveloperDocs", "codex-repo"):
        url = policy["mcp_servers"][name]["url"]
        parsed = urlsplit(url)
        if (
            any(char.isspace() or ord(char) < 32 for char in url)
            or parsed.scheme != "https"
            or not parsed.hostname
            or "*" in parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Managed MCP identity requires an exact HTTPS endpoint")
        expected = servers[name]["identity"]["url"]
        if expected == "@CODEX_REPO_URL@":
            servers[name]["identity"]["url"] = url
        elif expected != url:
            raise ValueError("Public MCP identity disagrees with canonical policy")
    output = POLICY.toml_document(requirements)
    if tomllib.loads(output) != requirements:
        raise ValueError("Requirements TOML round-trip mismatch")
    return rules, output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bindings", type=Path, required=True)
    args = parser.parse_args()
    try:
        policy = tomllib.loads(POLICY.render(args.bindings)["config"])
        # These synthetic paths are serialization examples, never install targets.
        rules, requirements = render_controls(
            policy, Path("/fixture/dots/codex"), Path("/fixture/home")
        )
        count = len(tomllib.loads(requirements)["mcp_servers"])
    except (KeyError, OSError, TypeError, ValueError) as exc:
        parser.exit(
            1,
            f"Controls generation refused ({type(exc).__name__}); inspect inputs locally.\n",
        )
    print(
        f"PASS: rendered {len(rules)} rule layers and {count} MCP identities; no files installed"
    )


if __name__ == "__main__":
    main()
