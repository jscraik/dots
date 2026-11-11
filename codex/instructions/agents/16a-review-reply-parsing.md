# CodeRabbit Review-Reply Parsing

> Public library port. Read [migration scope](../migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


Read only when PR readiness evaluates an authenticated CodeRabbit chat reply
for a current-head no-findings verdict. Ordinary Git mutations do not need
this parser contract.

CodeRabbit's authenticated chat-reply layout may wrap a standalone current-head
no-findings verdict in its fixed reply marker, optional standard tip and
analysis disclosure, one optional plain or inline-code user mention, and standard AI footer.
The installed-wheel verification disclosure must preserve provenance: its link must identify one authenticated CodeRabbit discussion in the active PR at the current head; missing, foreign, duplicate or stale evidence fails closed.
Require the linked source to contain the complete observed verification envelope, reply to the authenticated current-head metadata finding, and precede the clarification. An original finding, unrelated note or remaining-finding report is not verification.
State full head and base identifiers in the envelope and compare both with the active PR; unnamed identifiers cannot clear a changed base or replace missing provenance.
The complete fixed tip may precede the reply marker or follow it; permit one
tip only, and reject arbitrary prefixes or altered tip text in either order.
The mention may precede the verdict or occupy its own paragraph before or after
the analysis disclosure. An optional fixed `Learnings added` appendix after
the AI footer is decoration: require its complete disclosure, metadata fence
and standard note, and never use its payload as verdict evidence.
A fixed `Learnings used` disclosure may follow that appendix or appear alone
after the footer. Require its complete disclosure and metadata fence, admit
each appendix at most once in this order, and never read its payload as a verdict.
The fixed `Learnings used` disclosure may also appear immediately before the
standard AI footer; apply the same metadata and boundary checks in that order.
Parse those Markdown boundaries;
do not search arbitrary report text for a positive phrase. The verdict must be
outside quotes, code, and the analysis disclosure. Unknown HTML layouts, extra
verdict prose, service-error responses, and unavailable parsing dependencies
fail closed. Two complete static-inspection disclosure layouts also qualify:
the independent inspection report and its linked clarification. Require their
outer standalone full-head verdict, complete provenance, successful diff-check
statement, explicit non-execution/evidence limits, read-only authority limits,
and AI footer. Admit only the supported paragraph envelopes, not arbitrary
inspection prose or a verdict inside a provenance link. These disclosures
describe review evidence; they do not prove CI, runtime or merge readiness.
The fixed installed-wheel metadata-verification clarification qualifies only with its outer verdict, exact verification paragraph and GitHub PR discussion link, exact no-approval/no-merge disclaimer, and AI footer.
This clarification retains the required supported analysis disclosure; its verification link does not exempt it from that requirement.
The link explains the repair but supplies no clearance; unknown or additional paragraphs remain blocked.
The complete observed two-file memory/launcher source-inspection report and its
linked clarification also qualify. Require their exact paragraph/list envelopes,
standalone full-head verdict, base revision, explicit non-execution limits and
authority limits, and standard AI footer. Their fixed “both changed files” claim
must match `codex/config.toml` and `codex/scripts/validate-codex-hooks.sh` in the
committed diff. A clarification must link to an authenticated
complete source-inspection report in the same PR, never another clarification.
The report's hosted-result prose is not CI proof; live required checks remain
independently mandatory. Unknown sections, extra findings or altered limits fail
closed; this is not a general positive-phrase extractor.
When an analysis disclosure is present, validate it as a supported provider
tool trace or fixed benign status explanation. Free-form review narrative,
including findings, cannot be hidden behind a positive outer verdict; an unknown
disclosure requires inspection rather than automatic clearance. The observed
plain-mention reply may omit analysis only when that mention is its own complete
paragraph before the standalone verdict. Otherwise the wrapped chat-reply
requires an analysis disclosure containing at least one exact permitted
explanation or recognized command trace. Reject an empty, marker-only, or
output-metadata-only disclosure. The
two complete static-inspection report layouts are separate evidence forms and
may omit the chat analysis wrapper.
The `Script executed` label and shell fence language are not enough to make
fenced content a known trace. Admit only the observed single-command forms:
`git diff <full base> <full head> --stat`, a GitHub issue-comment API read, or
the fixed closing-tag `printf` fixture. Reject empty traces, narrative,
additional lines and unknown commands. This classifies returned evidence;
it neither executes the trace nor grants permission to execute it.
Bind a diff trace's revisions to the report's declared base and head; reject
the trace when that provenance is absent or different.
A fixed completed-source verdict may clarify that a limit affected only a
separate automatic action. Require the complete known six-paragraph envelope,
matching full heads, declared base/count and explicit execution/authority limits.
Bind its one-to-fifteen word count to the actual diff. This direct verdict cannot
serve as the full-inspection source of another clarification. An attached failed
action, actual quota failure, extra finding or unknown prose still fails closed.
The fixed inspection-request producer asks for the supported standalone verdict
outside the standard wrapper; only known traces or fixed status explanations qualify in analysis.
It explicitly forbids hiding findings or failed/incomplete inspection to fit a
format. This formatting request is not clearance; only authenticated returned
evidence and the unchanged readiness gates can supply it.
Before quorum, compare the disclosed file count with the complete committed
diff inventory, bind the disclosed base to this PR's expected base, require the
prior revision to be an ancestor of the full current head, and bind a
clarification link to this PR's authenticated full-inspection comment in the
complete inventory. Missing, stale, unrelated or unauthenticated provenance
fails closed even when another reviewer supplies ordinary clearance.

Parse replies in a disposable working directory using isolated Python and the
verified pinned distribution, never repository-local imports. Reuse a bounded
process-local cache of reply bodies across gate evaluations, including failed
parses. Timeout cleanup terminates the owned parser process group, including
wrapper descendants. Authenticate the CodeRabbit author before launching its
parser.

Unknown analysis blocks qualification even when its prose is not an execution
failure. Keep service-status detection separate from that boundary. Inspect
standalone service statuses and identified tool-output fences (an output label,
output length, or output/stdout/stderr fence tag), including known service-error
prefixes. Reviewed code and explanatory prose are not output. Preserve Markdown
line breaks and match complete prose responses, including recognized retry
instructions, rather than isolated explanatory lines. In identified tool
output, a known failure status followed by a colon and diagnostic detail
remains a failure; do not extend that rule to prose.

This adapter does not admit generic review summaries, another author, stale
verdicts, unresolved threads, or missing independent reviewers, and does not
grant deployment or merge authority.

The exact leading `<!-- codex-review-receipt:v1 -->` marker followed by a
blank line may decorate one supported Codex report or standalone verdict.
Remove that single prefix only inside the authenticated Codex adapters; retain
the complete report, head binding and footer checks. Duplicate, altered or
embedded markers and added findings remain unsupported. A marked security-only
report stays informational and cannot supply code-review clearance.

The authenticated Codex connector's fixed code-review no-issues report may
also qualify when its reviewed commit matches the current head and its complete
standard footer is intact. Extra findings, errors or unknown layout fail closed.
The exact optional `codex-review-receipt:v1` header and observed fixed endings
`Another round soon, please!` and `Bravo.` are supported; duplicate or unknown
receipt headers and unknown endings remain rejected. Security-only receipts
remain informational.
Recognise only the fixed report endings, including the observed `Breezy!`, `Swish!`,
`:rocket:` and `:+1:` variants; these endings do not replace the reviewed-commit
field, authenticated author or intact footer.
An exact historical no-issues report is not an unresolved finding, but cannot
grant current-head clearance or erase an earlier genuine finding.
Its exact current-head clearance statement `No findings for <full head sha>.`
may also qualify when any trailing text is only its known auto-appended footer
(a `View task` link and/or the About Codex in GitHub details block). Short
SHAs, other heads, extra prose, and other authors fail closed.
Its legacy activity-only summary and security-only no-findings report are
informational. Explicit versioned code completion follows the native route below.
An exact informational report stays neutral after the PR head advances; its
recorded commit must remain well-formed and internally consistent, but is not
clearance for either the old or current head.
Unknown, failed or incomplete reports retain ordinary blocking classification.

The authenticated Codex connector's two fixed usage-limit notices (the credits
settings notice and usage-dashboard notice) are unavailable evidence, not
findings or clearance. Require the complete fixed text and provider links.
They never fill reviewer quorum or erase earlier substantive concerns;
appended findings and unknown variants retain blocking classification.

For legacy activity-only layouts without a `codex-review-state:v1` header,
the supported code-only or combined code/security completion summary can qualify
when the live GitHub PR-issue-body reactions API reports a thumbs-up from the exact Codex bot
identity. Bind the summary's unique commit abbreviation to current HEAD and
require its update time from one second before to three seconds after completion.
Join only a reaction created within five minutes after completion. Collect all
pages, verify repository and author identity, then re-read the head and source
inventories to reject drift. Record the summary URL, full reviewed HEAD,
completion time and reaction identity in the receipt. Neither a copied summary,
another user's thumb, a historical thumb nor a security-only result qualifies.
Later findings and all other readiness requirements remain blocking; a later
quota-only response does not cancel this independently completed code review.
In the combined layout, validate the security metadata against its security row
and repository/PR identity; only the code row supplies code-review evidence.

The `codex-review-state:v1` header may supply explicit native code completion.
Require unique JSON keys, the exact full current code head, completed status,
literal false finding flags, and the complete supported matching code row/footer.
The observed collapsed `Codex Review Summary` details wrapper is presentation
only: its exact completed label and matching closing tag may surround the same
validated content. Extra prose, malformed nesting and unknown labels still fail.
The security state may be the exact all-null shape only when no security row or
security metadata exists. A completed security row with both finding flags null
is not eligible on its own, including for code-only quorum. It requires the
independently authenticated reports described below. Mixed null/false, true
flags, incomplete state, enabled merge gates and conflicting identities fail.
Only explicit false flags or the complete correlated native report join can
establish no findings; null alone never does.
Absent and legacy activity-only security results limit the completion
to `clearance_scope: code_only`. It may supply code-review quorum but cannot erase
any earlier untyped Codex concern, including a security finding. Required security
checks and all other gates remain independent. The receipt records code and
security evidence separately, including when another provider blocks readiness.
The uncorroborated-unknown-security extension is deferred in this public port;
the existing strict receipt regressions remain required.
Verify authenticated service identity, same-PR URL, timestamps and an unchanged
live inventory snapshot. Later security or metadata updates do not move the code
completion time; later findings still block. No optional reaction is required
for this explicit state.
A combined summary whose completed security finding fields are both null may
qualify only when the code state has both finding flags false and two exact,
unedited native reports independently corroborate the code and security results.
Require one report of each kind from the same authenticated Codex GitHub App and
bot, on the exact PR, with unambiguous reviewed commits resolving to the current
full head. Bind each report's creation time within three seconds of its matching
completed row, require code completion before security completion, and require
the summary update from one second before to three seconds after security
completion. Re-read the complete hosted inventory before accepting the join.
Count every other comment whose creation or update falls in either completion
window before filtering identity, receipt content or edit status. Exclude only
the authenticated summary itself, whose update is expected in the security
window. Unknown or inconsistent timestamps and ambiguous windows fail closed.
An unrelated coincident comment can therefore prevent the join. Verify GitHub's GraphQL
edit history for both exact receipt nodes and re-read it after the REST inventory
snapshot: their bodies, URLs and timestamps must match, `lastEditedAt` must be
null, `includesCreatedEdit` false and the edit count zero. The joined code receipt
is retained as source evidence but cannot act as a second, later clearance;
later and same-second findings are evaluated against the code completion time.
Missing, edited, duplicated, stale, inconsistent or finding-bearing reports
remain blocking; null fields alone never establish a clean security result.
Security-only evidence cannot independently fill the code-review quorum.
A verified CodeRabbit automatic summary is also eligible under the native
completion contract in Git/release governance. Generic chat remains informational.
Neither provider completion skips later-finding, thread, CI or quorum guards.

The exact native separate recent-status wrapper, 12px/16px review icons and
Organization UI configuration without repository YAML are supported metadata
variants. CHILL/Essentials labels describe configuration, not clearance.
Repository identity still comes from the authenticated same-PR source and all
range, coverage, run identity, status and snapshot checks remain required.
Unknown walkthrough, pre-merge, context and merge-risk prose remains blocking.
Diagnostics identify source URLs, body digests and unclassified sections without
qualifying them. Adjudication uses qualifying formal evidence, or the existing
authenticated `pr-repair-endorsement/v1` contract only where the owning repository
supports its protected CI route. Configs-only CI support does not authorise use in
SDK repositories. A local note,
digest or repeated status request cannot substitute for independent endorsement.

A historical Tessl approval that has been dismissed may remain neutral only
when its authenticated author and complete known zero-finding envelope match.
The known name-mismatch recovery narrative is supported for this historical
classification only. Unknown narrative, contradictory counters, malformed run
identity and findings remain blocking. Neither dismissal nor zero counters alone
prove a clean review. Historical neutrality never provides current-head review
coverage, quorum or clearance of an earlier finding.
