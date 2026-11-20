# 1Password CLI, Environments, MCP, and Git Signing

> Public library port. Read [migration scope](migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


1Password is the approved key manager for Codex authentication material and
Git signing. Keep secret values inside 1Password. Use the bounded wrapper or
the 1Password MCP tools described here; never copy values into prompts,
command output, tracked files, or ad hoc shell exports.

## Table of contents

- [Managed tool identities](#managed-tool-identities)
- [Stable agent FIFO procedure](#stable-agent-fifo-procedure)
- [Beta Environment procedure](#beta-environment-procedure)
- [Codex MCP workflow](#codex-mcp-workflow)
- [Validation and failure boundaries](#validation-and-failure-boundaries)
- [Git signing](#git-signing)
- [References](#references)

## Managed tool identities

- Stable CLI: `op` is the canonical Codex-agent CLI for the Desktop-owned
  `~/.codex/.env` FIFO and `op run --env-file` workflow.
- Beta CLI: `op-beta` remains the explicit host-session CLI for the beta
  `op run --environment` workflow. Mise manages and checksum-pins it through
  `${CONFIGS_CHECKOUT}/mise/config.toml` and `mise/mise.lock`.
  Install or repair it with
  `mise install --locked "http:op-beta" --yes`; do not download an unpinned
  beta directly or alias `op-beta` over `op`.
  The guarded wrapper also requires non-writable `/opt/homebrew/bin/op-beta` or
  `/usr/local/bin/op-beta` under that root; mise alone is insufficient.
- MCP: Codex registers the signed binary at
  `/Applications/1Password.app/Contents/MacOS/onepassword-mcp` as the
  `1password` MCP server. The tracked `codex/config.toml` keeps it enabled for
  the normal Codex profile and disables it in the four OSS profiles that must
  not inherit private integrations.
- Desktop app: enable **Settings > Developer > Integrate with 1Password CLI**
  and the 1Password MCP integration through the app. Never edit the app's
  signed settings file directly.

Keep the three identities distinct. A working MCP connection does not prove a
child-process injection route, a successful FIFO command does not prove the
beta XPC route, and a successful host beta command does not prove that Codex's
sandbox can reach 1Password Desktop.

## Stable agent FIFO procedure

1Password Desktop owns `${CODEX_HOME}/.env` as a UNIX named pipe.
It supplies the selected Environment only when a child process opens the FIFO
and remounts it after Desktop restart. Configs never creates, copies, sources,
or writes plaintext to that path. Codex agents use the checked-in wrapper,
which rejects a missing path, a symlink, a non-FIFO, the wrong owner, or any
group/other permission before invoking stable `op`:

```sh
bash ${CODEX_POLICY_SOURCE}/scripts/run-auth-backed.sh \
  --env-file ${CODEX_HOME}/.env \
  --canary OLLAMA_API_KEY
```

Both networked permission profiles explicitly deny the FIFO. The two exact
fixed-output canary commands are the only auto-allowed FIFO routes; any
credential-bearing child requires normal outside-sandbox approval. Ordinary
workspace children therefore cannot open the credential channel directly.

The canary prints only a fixed pass/fail result. When a child needs a secret,
require its name without exposing its value and keep the injected material in
that one short-lived process:

```sh
bash ${CODEX_POLICY_SOURCE}/scripts/run-auth-backed.sh \
  --env-file ${CODEX_HOME}/.env \
  --require-env REQUIRED_VARIABLE_NAME \
  -- command arg
```

The 1Password FIFO is reusable across sequential opens but does not support
concurrent consumers. Catalog discovery, A, B, and any later authenticated
stage must each start a fresh wrapper invocation after the preceding stage has
exited. Never keep a shared file descriptor, background two FIFO consumers, or
read the FIFO with `cat`, `source`, Python, Node, `env`, or `printenv`.

## Beta Environment procedure

The approved beta Environment is **AGENTS ENV**. The managed beta CLI invokes
`op-beta run --environment` through 1Password Desktop's signed XPC helper. It
is an explicit host-terminal route, not the Codex-agent sandbox transport.

Use this procedure:

1. Open and unlock 1Password, then enable **Settings > Developer > Integrate
   with 1Password CLI**.
2. Confirm the lock-matched beta and the protected `/opt/homebrew` or `/usr/local`
   recipient above. Mise can repair its copy from the lock, but not that recipient:

   ```sh
   command -v op-beta
   op-beta --version
   mise install --locked "http:op-beta" --yes
   ```

3. Resolve the **AGENTS ENV** Environment UUID from the 1Password UI or a
   names-only MCP lookup. Treat it as routing metadata and keep it out of
   tracked files, shell profiles, logs, and command output.
4. In a trusted host terminal, bind the UUID only to the wrapper invocation and
   run the fixed-output canary for an allowlisted variable:

   ```sh
   CODEX_AUTH_ENVIRONMENT_ID='<your Environment UUID>' \
   bash ${CODEX_POLICY_SOURCE}/scripts/run-auth-backed.sh \
     --require-environment \
     --canary OLLAMA_API_KEY
   ```

5. Run a credential-bearing child in the same process-scoped form, requiring
   each variable by name without printing its value:

   ```sh
   CODEX_AUTH_ENVIRONMENT_ID='<your Environment UUID>' \
   bash ${CODEX_POLICY_SOURCE}/scripts/run-auth-backed.sh \
     --require-environment \
     --require-env REQUIRED_VARIABLE_NAME \
     -- command arg
   ```

`--require-environment` validates the ID, selects managed `op-beta`, and refuses
FIFO fallback. Status 69 means only the writable mise copy is present. The child
receives the Environment; the parent does not. Use one fresh wrapper invocation per child.

If the beta route cannot connect to 1Password Desktop while the stable FIFO
canary passes, classify the failure as host-XPC reachability. Reopen or unlock
1Password and recheck Developer CLI integration. Do not treat it as an invalid
Environment, a missing secret, or a reason to add Unix-socket access, a sandbox
bypass, or a broader execpolicy rule.

Never validate either route with `env`, `printenv`, `set`, shell tracing,
`op environment read`, or a command that prints a secret. Arbitrary
credential-bearing children retain normal command approval; the wrapper is a
safe injection boundary, not a blanket authorization.

## Codex MCP workflow

Use the 1Password MCP for Environment metadata and deliberate management
operations. In a new Codex task:

1. Discover the deferred 1Password tools with `tool_search` using a query such
   as `1Password Environments authenticate list variables`.
2. Read the MCP getting-started and Environments guidance exposed by the
   connector before the first operation.
3. Call `authenticate`.
4. For the approved Environment, use a names-only variable listing with
   Environment ID from `CODEX_AUTH_ENVIRONMENT_ID` when discovery is needed.
   Never request, echo, summarize, or store values.
5. Treat create, append, rename, local `.env` creation, and any other mutation
   as explicit-write operations. Perform them only when the user has requested
   that exact change and the target has been resolved read-only first.

MCP authentication and a names-only lookup are the focused readiness proof.
They establish that Codex can identify and call the 1Password tool; they do
not expose Environment contents and do not prove beta CLI injection.

## Validation and failure boundaries

Run value-blind checks:

```sh
command -v op
op --version
command -v op-beta
op-beta --version
mise install --dry-run --locked "http:op-beta"
codex mcp list
```

For installed macOS binaries, also verify the Apple signature and
`TeamIdentifier=2BUA8C4S2C`. Keep the exact version, archive URL, and checksum
in the mise config and lockfile rather than relying on a moving `latest` beta.

If CLI integration reports that it cannot connect to the 1Password desktop
app:

1. Run the canonical FIFO canary first. If it passes, the agent injection route
   is healthy and no XPC, socket, rule, or sandbox repair is required.
2. If the FIFO is missing, confirm 1Password Desktop's local `.env` destination
   is `${CODEX_HOME}/.env`, then restart or unlock Desktop so it can
   remount the FIFO. Configs must not create a replacement regular file.
3. If the FIFO metadata is rejected, inspect only `lstat`-style metadata. The
   path must be a non-symlink FIFO owned by the current account with no group/other access.
4. Only when the explicit beta host route is required, confirm the app is open
   and unlocked and the Developer CLI integration is enabled. On macOS that
   route uses signed XPC through 1Password's helper, not a Linux Unix socket.
5. A beta host failure does not invalidate a passing FIFO route and does not
   justify an execpolicy sandbox bypass. Repair the Desktop XPC session only
   for consumers that explicitly require `--environment`.

Skills SDK cloud A/B runs use that same canonical checked-in chain. Catalog
discovery uses Ollama's public model-list endpoint without loading a credential.
Each credential-bearing A/B variant starts a fresh `--env-file
${CODEX_HOME}/.env` invocation through the repository wrapper and
`run-codex-exec.sh`, and the stages run sequentially. Do not point SDK execution
at copied home-directory wrappers, share a FIFO descriptor, or start concurrent
consumers.

Do not disable authentication, weaken app settings, edit signed app state,
export secrets, allow Unix sockets speculatively, or add a broad wrapper rule.
An arbitrary command after `run-auth-backed.sh` must remain outside the allow
rules. A passing host canary, FIFO canary, `codex mcp list`, or MCP
authentication proves only its own lane; Codex-agent injection is proven by
the fixed-output FIFO canary in the current task.

## Git signing

Use native Git with 1Password's official commit-signing program. Configs does
not own a Git client, signing broker, LaunchAgent, socket protocol, repository
registry, or signing wrapper. Commit signing is independent from stable `op`
FIFO injection, beta `op-beta --environment`, and the 1Password MCP workflow
used for API keys.

The accepted source architecture is recorded by
`docs/adr/0001-native-git-1password-signing.md` (Configs dependency: `../../docs/adr/0001-native-git-1password-signing.md`).

### One-time per machine

```bash
git config --global gpg.format ssh
git config --global gpg.ssh.program /Applications/1Password.app/Contents/MacOS/op-ssh-sign
git config --global user.signingkey "<1Password public SSH signing identity>"
git config --global commit.gpgsign true
git config --global gpg.ssh.allowedSignersFile ~/.config/git/allowed_signers
```

Prefer 1Password's **Configure Commit Signing** and **Edit Automatically** UI
to write these values. The signing key is public metadata; private key material
stays in 1Password and must never be printed, copied, or stored in Configs.

Create `~/.config/git/allowed_signers` as an owner-only mode-0600 local trust
store. Its single approved entry uses the configured `user.email` principal,
the `git` namespace, and the same public SSH key written by 1Password's
**Configure Commit Signing** flow; never copy private key material into this
file. The entry format is:

```text
<user.email> namespaces="git" <1Password public SSH signing identity>
```

### Per-session checklist

1. Open and unlock 1Password.
2. Confirm Git's value-blind configuration:

   ```bash
   test "$(git config --global --get gpg.format)" = ssh
   test "$(git config --global --get commit.gpgsign)" = true
   test "$(git config --global --get gpg.ssh.program)" = \
     /Applications/1Password.app/Contents/MacOS/op-ssh-sign
   test "$(git config --global --get gpg.ssh.allowedSignersFile)" = \
     "$HOME/.config/git/allowed_signers"
   ```

3. Stage only explicitly owned paths. On macOS, ask Codex to run the exact
   normal `git commit` through its bounded host-capable execution path. Do not
   first attempt the commit in the default sandbox: that environment cannot
   reach 1Password Desktop, and an allow decision for the command does not widen the
   sandbox's IPC boundary. Auto-review may approve the host-capable request when
   the named repository task authorizes the commit. Git still runs the
   repository's normal hooks and calls `op-ssh-sign` for the signature.
4. Run `git verify-commit HEAD` and require it to pass against the configured
   local allowed-signers file before any push. GitHub's verification surface is
   additional hosted evidence; it does not replace the local check.

If the host-capable commit still cannot reach the signer, preserve the staged
index, stop with the branch unchanged, open and unlock 1Password, confirm CLI
integration, and retry the same normal host-capable commit. Never fall back to
an unsigned commit, disable `commit.gpgsign`, bypass hooks, expose the signing
socket to the general sandbox, or add another wrapper or daemon.

A disposable signing canary is valid only when `git verify-commit HEAD` passes
locally before the canary repository is removed. Do not push a canary.

Pushes and GitHub mutations are separate capabilities and do not receive the
signing authority. They retain execution approval unless Codex supplies an
unforgeable, expiring task grant. A caller-provided flag, environment variable,
task ID, or prose assertion is not a grant.

The SSH agent may still be used normally for authentication outside this commit
signing flow, but commit signing itself uses `op-ssh-sign`. Do not inspect or
export private keys, print agent identities during routine commits, sign raw
bytes, sign tags without separate authority, or treat local signing as remote
write authorization.

## References

- [1Password CLI](https://www.1password.dev/cli)
- [1Password CLI app integration](https://www.1password.dev/cli/app-integration)
- [1Password Environments](https://www.1password.dev/cli/secrets-scripts)
- [Use a local `.env` file](https://www.1password.dev/environments/local-env-file)
- [Validate local environment mounts](https://www.1password.dev/environments/agent-hook-validate)
- [Secure AI agent access](https://www.1password.dev/get-started/secure-ai-access)
- [1Password SSH agent](https://developer.1password.com/docs/ssh)
