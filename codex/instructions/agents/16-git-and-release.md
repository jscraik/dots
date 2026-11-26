# Git and Release Governance

> Public library port. Read [migration scope](../migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


Read before Git mutations, PR delivery, thread reconciliation or merge-readiness
claims. This reference owns the detailed procedures routed from the global
baseline; its safeguards apply only to the selected authorized workflow.

## Table of Contents

- [Git authority and signing](#git-authority-and-signing)
- [Receipts, review and worktrees](#receipts-review-and-worktrees)
- [Provider-generated PR descriptions](#provider-generated-pr-descriptions)

## Git authority and signing

- Native Git uses 1Password's official `op-ssh-sign` program for commit
  signatures. The accepted source architecture is recorded in
  `docs/adr/0001-native-git-1password-signing.md`. Direct Work may stage only
  explicitly owned paths and create a normal signed commit on the current
  non-protected task branch with `git commit`. On macOS, request the bounded
  host-capable execution path for that exact normal commit directly; do not
  first attempt it in the default sandbox, which cannot reach 1Password
  Desktop. Auto-review may approve this boundary crossing when the named
  repository task authorizes the commit. Preserve the index on failure and run
  `git verify-commit HEAD` after success and before any push. Do not introduce
  a signing wrapper, broker, LaunchAgent, repository registry, alternate socket
  protocol, unsigned fallback, or signing-specific execpolicy rule.
- Normal commit hooks run through Git. This authority does not include
  unrelated dirty paths, owner-unknown files, amend/rebase/reset, hook bypasses,
  tags, protected refs, unsigned fallback, or any remote mutation.
- Fetches and read-only GitHub or pull-request inspection remain routine local
  evidence work. Pushes, pull-request creation or updates, comments, reviews,
  merges, releases, workflow dispatches, repository settings, and secrets are
  remote mutations. Require the matching explicit user request and retain the
  execution approval unless Codex supplies an unforgeable, expiring grant bound
  to the task, repository, branch, operation, and destination. Caller-supplied
  flags, environment variables, task IDs, and prose are not such a grant.
- A user request that names a repository or candidate, source branch or ref,
  target branch, PR operation, and merge conditions authorizes the normal
  bounded PR lifecycle it explicitly requests. Continue non-force source-branch
  pushes, receipt-gated PR creation, named exact-head review requests, read-only
  polling, verified current-head finding reconciliation within scope, same-branch
  signed follow-up commits, and receipt-gated normal merge without duplicate
  authorization. Stop for repository, branch, destination, scope, mutation,
  risk, or merge-condition changes. Force pushes, protected-branch pushes,
  bypasses, admin merges, branch deletion, and unverified review-state mutation
  remain outside that lifecycle authority.

## Receipts, review and worktrees

### Operation-bound lifecycle transitions

The GitHub-only `pr-readiness.py --lifecycle` route is separate from merge
readiness. It supports exactly `ready`, `reopen`, and supersession `close`.
Matching user authority and execution approval remain required. It cannot
merge, submit a review, edit a body, post a comment or delete a branch.

Prepare with `--expected-repo OWNER/REPO --expected-pr NUMBER
--lifecycle-head FULL_SHA --scope-file REPO_RELATIVE_PATH --write-receipt`.
For `close`, also supply `--replacement-pr NUMBER`: the replacement must already
be merged into the same selected base, with verified merge ancestry, and its
description must retain an exact two-cell coverage row:
`| https://github.com/OWNER/REPO/pull/NUMBER | FULL_ORIGINAL_SHA |`.
Separate mentions or mismatched rows do not prove the mapping. Keep the
original branch and history. This route does not turn the superseded PR's
failing CI into a pass.

Read the prepared `pr-lifecycle/v1` receipt before applying it. It binds the
operation, current hosted target and pre/post states, repository/host, local
checkout identity, scope digest and replacement evidence. It expires after
five minutes. Use the same arguments with `--apply-lifecycle`; the helper
rechecks immediately before its single fixed mutation and verifies the resulting
state and unchanged head/base afterward. A failed readback reports uncertainty;
inspect the actual hosted state before preparing another transition.

These receipts make no CI, review, thread-resolution or merge-clearance claim.
`ready` may start review with outstanding findings. Direct lifecycle commands
remain blocked, even with a passing update receipt. Comments retain their
existing exact-body/review-request routes. Merge, body editing and review
submission retain the gates below. This source contract grants no installation
or activation authority.

### Existing delivery receipts

- Before `gh pr create`, require
  `python3 ~/.codex/scripts/pr-readiness.py --phase create --scope-file <scope-file> --write-receipt`;
  before PR update (except the body-only repair below) or merge-readiness
  claims, require the `--phase update` receipt. The projected
  `pr-readiness-guard.sh` enforces this on shell routes where rejection has
  been verified. Do not infer connector enforcement from a shell-hook result.
- Review inspection can proceed with pending, failed, missing or unknown CI;
  its receipt records the observed CI outcome and proves no acceptance or merge
  readiness. Current published identity and HEAD remain mandatory. Evidence-backed
  thread reconciliation permits pending CI but still blocks failed, missing or
  unknown check evidence. Update receipts and merge readiness continue to
  require all current-head checks and final review gates to pass. Receipt
  consumption rechecks hosted identity, CI state and target-thread eligibility.
- An explicitly authorised independent review request or verdict clarification
  may use a `--phase review_inspection --scope-file <scope-file> --write-receipt`
  receipt, followed by
  `python3 ~/.codex/scripts/pr-review-request.py --repo <owner/name> --pr <number> --reviewer <codex|coderabbitai>`.
  Run the helper with `--dry-run` first. For a non-default target, pass the same
  `--base <branch>` to the receipt producer and request helper; receipt
  consumption verifies that target. Codex requests use the documented
  `@codex review` trigger; CodeRabbit requests use `@coderabbitai full review`
  for complete candidate coverage. CodeRabbit clarification requires `--clarify` and
  `--clarify-source <issue-comment-url>` identifying one authenticated source
  in this exact PR mentioning the current full head. The fixed clarification message asks
  whether the automated CodeRabbit code review recorded at that source completed;
  it never presumes completion or clearance. It requests the recorded review
  outcome without launching another inspection. The response is informational
  status only and must not supply a clearance verdict or approval. The collector
  retains denial-only provenance from exact unedited hosted user requests even if
  their source disappears or readiness uses a different authenticated account. Record-only replies cannot clear review
  concerns or count towards quorum, even if the provider emits a no-findings
  statement. Only complete recognised benign status is neutral; reported
  findings and unknown content remain blocking. A later full-inspection request
  cannot make an ambiguous delayed chat reply independent; use qualifying formal
  review evidence instead. CodeRabbit conversational issue comments remain informational:
  edited or deleted request history cannot turn chat into clearance. A verified
  automatic completion summary may qualify through the provider adapter below.
  New requests still require the authenticated requester's
  identity; evaluator changes never grant clearance. Independent review clearance
  still requires its own qualifying evidence.
  Codex clarification is not supported by this helper. Its fixed message
  requests inspection evidence only.
  After CodeRabbit reports an incomplete rate-limited review for the exact
  current head, the helper may retry the free full-review request with
  `--retry-unavailable-source <issue-comment-url>` once that authenticated
  response is at least one hour old. The source must belong to the same PR;
  the source-bound request is deduplicated and never enables paid reviews.
  A supported SHA-less quota notification may bind to one unedited canonical
  current-head request by the authenticated actor within the preceding sixty
  seconds, with no competing invocation. Require the fixed CodeRabbit identity,
  complete notification format and unchanged request/reply records at consumption.
  This temporal association permits inspection only; it proves no provider
  linkage, completed review or clearance. Wait at least one hour or the stated
  allowance delay, whichever is longer. This evidence does not establish billing
  policy; verify included capacity and the existing paid-continuation boundary
  before consuming it. Request wording cannot enforce provider billing.
  If a later authenticated CodeRabbit concern leaves the same head outstanding,
  use `--reinspect-source <issue-or-inline-comment-url>` for one fresh full inspection.
  This route requires that exact PR's current-head bot concern to follow an
  authenticated original request and remain outstanding in the live review
  inventory. An inline source must be a uniquely identified authenticated
  CodeRabbit review comment, not a thread reply, on the exact PR, with both its
  original and current commit equal to the current head; it must follow all
  other full-review requests. Each source check binds the PR base branch and
  commit to the inspection receipt, which is revalidated before a final source
  and duplicate check. The helper rechecks the source before posting,
  reuses an existing authenticated, unedited request only when it follows the
  finding's latest update, and rejects older findings after a different later
  full-review request. It cannot combine with
  clarification, accept arbitrary request prose, waive clearance, or request
  reinspection after clearance.
  The receipt retains clean checkout, current published head/base, declared
  scope and the phase-specific CI requirements above, but does not require reviews to have
  cleared or threads to remain open. Consumption rechecks these facts and
  verifies the open PR. It admits no source/body updates, review submissions,
  thread replies/resolutions, approval or merge. Normal execution approval is
  still required. An inspection receipt cannot replace an update receipt.
- A separately authorised post-merge validation-evidence thread may use the
  delivered `codex/scripts/pr-post-merge-reconciliation.py` helper after its
  normal PR validation and independent review. This does not relax the existing
  open-PR receipt route or grant retrospective review or merge clearance.
  The operator must independently adjudicate the exact original comment as
  validation-evidence-only and bind its ID and SHA-256 body digest. Do not use
  this route for security, correctness or other unresolved substantive findings.
  `--evidence-only` records that selection; it grants no authority.
  Require normal user authorisation and execution approval for both mutations.
  Supply explicit `--repo-root`, `--repo`, `--pr`, `--thread`, `--run`,
  `--source-comment`, `--source-sha256`, `--evidence-only` and a disposable
  `--receipt` path. First use `--dry-run`, then `--write-receipt`, then
  `--execute` with identical target arguments after passing preflight.
  The fixed reply and complete evidence are bound in a ten-minute receipt.
  Never use it to admit raw GraphQL, arbitrary prose or broader mutations.
  This narrow route requires a clean accepted checkout and remote `main` exactly
  at the authenticated single-parent merge, with its complete tree identical to
  the reviewed head. Tree identity covers blobs, modes, symlinks and deletions.
  Require all current-head checks and the successful authenticated validation
  workflow run to match. The supported GitHub Actions workflow is
  `.github/workflows/validate.yml`, linked by its unique `validate` check.
  Its reviewed content must match the supported immutable workflow digest.
  The receipt binds the authenticated job and successful executed steps to the
  exact quality, tests, build, installed and diff commands in the fixed reply;
  skipped or ambiguous steps cannot prove a command outcome.
  The run must identify the target PR; an empty association list is admitted
  only when the complete commit-associated PR inventory contains exactly that PR.
  Unknown later thread comments require separate adjudication and are rejected.
  Allow zero or one matching authenticated evidence reply; reject duplicates
  before mutation and during reply readback.
  The helper verifies the exact authenticated reply before resolving, then
  recollects the complete evidence after resolution. If mutation was requested
  but its outcome cannot be verified, preserve `status: blocked` and the precise
  `mutation_outcome`; inspect live state before retrying. Never infer rollback.
  Every result retains `acceptance_claims_proven: false`.
  The Configs review-helper maintainer owns this route. Its regression suite is
  listed explicitly in `pnpm test:codex-policy`; the maintained wiring checker
  verifies that entry without executing the suite itself.
  Focused proof uses `python3 -m unittest codex/scripts/tests/test_pr_post_merge_reconciliation.py`.
- Explicitly authorized, body-only metadata repairs may use
  `python3 ~/.codex/scripts/pr-body-refresh.py --pr <number> --repo <owner/name> --body-file <file> --repair`
  when metadata checks prevent a passing update receipt. Require matching
  repository, open PR and current local/hosted HEAD, a template-valid proposed
  description with truthful validation evidence, and normal execution approval.
  Repositories without a PR template may supply a nonempty description only
  after the helper verifies template absence in Git HEAD; a missing tracked
  template or an unsupported alternate template remains blocking.
  First run the helper with `--repair --dry-run`; then apply only the approved
  body with the same helper. Fetch the hosted description after saving, verify
  it matches the approved body and the head is unchanged, and refresh affected
  metadata checks. A failed verification is not a completed repair.
  This permission does not authorize code changes, other PR metadata changes,
  review-thread resolution, or merging. Reconciliation retains its own passing
  receipt; other updates and merge-readiness claims retain the full update
  receipt. A repair preflight is not readiness proof or a check/review waiver.
- For applicable solo-maintainer repositories, the readiness gate derives risk
  from the complete committed diff. Ordinary changes require CodeRabbit
  (`coderabbitai`) or Codex (`chatgpt-codex-connector`); high-risk changes require
  both. Zero unresolved threads and passing required checks remain mandatory.
  Ordinary includes application source, tests, formatting helpers and routine
  configuration. Security/authentication, governance and review gates, CI and
  runner privileges, releases/deployment, migrations, dependency manifests,
  new executable permissions, symlinks/submodules and unclassified files require
  two independent reviews. A stable executable formatting helper is ordinary;
  a filename such as design `tokens.json` is not an authentication boundary.
  The implementation author cannot supply either independent review. A second
  human maintainer is not required. Content review can still identify consequential
  risk that a path-based classifier cannot infer.
  Once the bot-quorum check classifies the diff, its result reports the
  paths and reasons that drive the tier, the qualifying reviewers and the
  remaining count. A current-head Codex App summary reporting an in-progress review
  directs the operator to refresh after that review completes. A completed
  summary with unknown security flags directs the operator to the existing
  correlated reports or a later qualifying review. Both conditions keep the
  evidence gate closed until independent proof qualifies.
  Without verified repair evidence, only those exact identities and
  current-head `APPROVED` or `COMMENTED` submissions/comments carrying explicit
  no-findings text bound to the full or abbreviated HEAD SHA count. Bare or
  blank submissions (including blank `APPROVED`), quota/rate-limit/error
  responses, stale, unknown, human, or `CHANGES_REQUESTED` reviews do not
  satisfy the bot quorum. A current-head human `APPROVED` review remains valid
  through the strict human-approval path.
- Native completion needs no duplicate clearance. A later empty current-head CodeRabbit approval
  must not replace an already verified current-head native completion with an
  empty verdict. Keep the original completion timestamp and all later-finding
  checks; an empty approval alone remains insufficient.
  Validate Codex state using the
  [reply-parsing contract](./16a-review-reply-parsing.md). CodeRabbit automatic evidence
  supports metadata-only and structured summaries: require the automatic envelope,
  no-actionable outcome, repository/run identity,
  current-head range and coverage. Classify full coverage using the verified Git merge base;
  retain live base snapshots and remote ancestry. Incremental ranges need an available
  ancestor start and earlier qualifying CodeRabbit PR review there; otherwise inspect fully.
  Incremental completion cannot erase prior findings without full/formal or verified repair.
  Validate every section. The metadata-only route admits only empty review-detail
  sections or count-matched literal LGTM records. The structured route also admits
  named Additional context used, Summary, minimal-risk explanation and passed
  pre-merge-check explanation regions. Preserve their complete raw source in the
  completion evidence; these regions are information, never independent clearance.
  Unknown outer structure, findings, failed checks and incomplete review remain
  blocking. Optional provider controls must be recognised and unchecked.
  A literal `<br>` is formatting within the recent-review section; attributes
  and surrounding unknown prose are not discarded.
  The supported presentation/configuration variants are defined in the parsing
  contract. A completed native review with unclassified narrative needs existing
  authenticated repair-endorsement where its repository CI route is supported,
  or qualifying formal evidence, not repeated
  inspection merely to obtain different wording. Source-digest diagnostics do
  not count as endorsements or clearance.
  Quoted fields cannot supply identity/coverage; file lists need their declared positive count.
  Join one same-app successful status within five seconds; re-read its append-only inventory
  and use the earlier timestamp. This commit-scoped temporal join has no run/PR identifier;
  each PR needs its own authenticated source/run UUID/head coverage. Reject missing,
  ambiguous, stale-time or different-app events. Edits cannot move clearance later.
  Structured summaries instead require one native CodeRabbit app Check Run for
  the exact repository, PR, head and base, with all inspection phases completed
  successfully and no annotations. Require full selected-file accounting.
  Authenticate the complete summary edit history, including the original record;
  its latest terminal revision must equal the current body and immediately follow
  this run's unique pending revision. Match both start and completion within five
  seconds, retaining the earlier immutable completion time. Summary and Check Run
  UUIDs identify separate provider records and are not presumed equal. Reject
  truncated/deleted history, changed sources and ambiguous matches. A contiguous
  same-run refresh may add or remove only the validated approval-policy metadata;
  all other review text must remain byte-identical and clearance retains the
  original terminal revision's time. Native UI pending metadata may say the
  commit is unavailable only when the official App check independently binds
  the exact repository, PR, head and base. In-progress summaries can retain an older
  no-actionable statement and cannot supply completion. Re-read native sources.
  Canonical hosted PR URLs may identify repositories if local lookup fails. Re-read the
  complete repository/PR/head/review/comment/finding snapshot before normalising completion.
  Unknown verdict prose, incomplete reviews, later/same-second findings, open threads, changes
  requested, CI and risk quorum still block. Keep diagnostics visible; they prove no CI success.
  An authenticated fixed `Action performed` / `Full review finished.` command
  notification is informational only. It neither supplies quorum nor cancels
  findings; added text, another actor or an unknown notification stays blocking.
- Legacy Codex activity-only summaries still require the completion/reaction
  join below; a bare reaction or an activity summary without explicit outcome
  remains insufficient. Do not demand another review solely for custom wording.
- The Codex connector's completed code-review summary may also qualify when
  joined to its authenticated PR-issue-body thumbs-up for the same completion.
  This supported layout does not use summary-comment reactions. Require an
  unambiguous current-head commit, the complete supported provider layout,
  summary update time from one second before to three seconds after completion
  (GitHub rounds timestamps and persists the provider update asynchronously),
  and a reaction within five minutes after
  completion. Re-read the complete paginated comment, finding, review and
  reaction inventories and hosted head before accepting the pair. A summary
  or reaction alone is not clearance; later findings still block. A later
  quota response does not undo a separately verified completed review.
  Findings in the same coarse GitHub second as a synthetic completion remain
  unresolved regardless of inventory order. An unavailable optional reaction
  leaves the completion nonqualifying, without blocking an independently
  sufficient quorum; missing required coverage and findings still block.
  The combined code/security layout must validate its security metadata against
  its security row and the exact repository/PR. Only the code row supplies code
  clearance; an older completed security row cannot supply a current code head.
  Unknown security finding flags require the separately corroborated code and
  security receipt join defined in the reply-parsing contract; null flags alone
  never establish a clean result.
- Only when evaluating an authenticated CodeRabbit chat reply for PR readiness,
  follow [review-reply parsing](./16a-review-reply-parsing.md). That adapter
  does not waive the reviewer, thread, check, or merge requirements above.
- Completed reviews with findings may qualify through the implemented repair
  lane only with authenticated independent current-tree endorsement, immutable
  finding-specific proof and protected CI provenance. Verify original reviewed
  commits against current ancestry, exclude the PR author, and recheck hosted
  identity, checks, decisions and threads after provider verification. Missing
  dependencies or deployment block this route. Author dispositions and resolved
  flags alone never grant clearance; uncovered changes and active requests for
  changes remain blocking. Do not require a blanket new no-findings response
  solely because independently verified repairs advanced the commit identifier.
- Treat worktrees as materialized checkouts with shared Git administration. Use
  `git worktree list --porcelain` with `git status --short` for read-only
  inventory. Roll back only a failed worktree created by the current invocation;
  preserve dirty, locked, or owner-unknown worktrees.
- The Git metadata lock/authority check is globally projected at `~/.codex/scripts/git-metadata-preflight.py`; project-local `codex/scripts/git-metadata-preflight.py` files take precedence, and compatible worktree bootstrap helpers should fall back to the projected copy when the local copy is absent.


## Provider-generated PR descriptions

Codex follows this workflow when it drafts, reviews, or repairs a Dependabot
or Codex Security PR. Apply the active repository's own template and evidence
requirements. Where the repository uses a **Validation Evidence** check, use
the criteria below for both writing and review.

1. Read the hosted PR, capture its head commit, and confirm its provider using
   the evidence below before applying provider-specific description criteria.
   Use the ordinary PR workflow when the source is unconfirmed.
2. Preserve the provider's description, release links or finding reference,
   and attribution. Add the missing evidence to the active repository's
   validation section or to a short maintainer section when permitted. Use
   only the repository's supported body update route.
3. Review the diff and validation on the same head. For Dependabot, inspect
   the manifest and lockfile changes, including related resolution changes
   and compatibility with the repository's supported versions. For Codex
   Security, check that the fix restores the affected boundary and that
   focused regression evidence exercises it. Recheck evidence after a head
   change. Consolidate missing description evidence into one actionable
   finding and keep substantive code or security findings visible.

- **Dependabot** must identify the dependency or group, the affected manifests
  or lockfiles, and the relevant version changes. Add compatibility or advisory
  context where it affects the bump. Identify Dependabot using the GitHub bot
  author supplied by the host.
- **Codex Security** must link the finding or provide its stable identifier,
  describe the affected boundary and intended fix, and distinguish generated
  static verification from validation actually executed on the candidate.
  Some Codex Security PRs are opened as the maintainer. Confirm the finding's
  association through the provider or the maintainer; a label, title prefix,
  branch name or template heading alone cannot establish provenance.
- **Both** must record concrete repository validation commands and their
  outcomes, or link hosted validation that identifies the commit and provides
  the check name and result. Tie successful evidence to the current PR head.
  List missing or blocked validation explicitly. An unchecked list of proposed
  tests, release notes, an advisory, or static analysis alone does not establish
  executed validation. Exact author-template headings are optional for
  confirmed provider-generated descriptions when repository policy permits.
- **All other PRs** use the repository's ordinary description criteria. Apply
  the normal exact-head CI and review rules and unresolved-finding gates to
  every PR. Provider authorship never gives review credit or waives checks.

When the producer cannot write the evidence section, use the guarded body-only
repair route above. The shared `codex/instructions/PULL_REQUEST_TEMPLATE.md`
is authoring guidance. Its presence alone does not cause the helper to detect
a GitHub template. Before template-free repair, the helper checks both the
candidate tree and the hosted default branch commit for tracked templates.
A tracked repository template requires the applicable structure validation or
blocks the unsupported alternate path.
