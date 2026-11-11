# Protected review repair evidence

> Public library port. Read [migration scope](migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


Use the endorsement contract (Configs dependency: `../docs/review-endorsement-contract.md`) and
readiness consumer (Configs dependency: `../docs/readiness-repair-consumer.md`) as the canonical
acceptance references. Independent complete-tree endorsement and finding-specific
proof remain mandatory; tests, author records and resolved flags do not replace them.

The protected producer `codex/scripts/verify-review-repairs.py` runs only on
`codex/repair-verifier` in CircleCI's `repair-verification` workflow and
`verify-review-repairs` job, using the restricted `configs-repair-verifier` context.
It fetches candidate Git objects without executing candidate code and emits
`repair-evidence/pr-N.json` with no merge authority. Invalid trusted endorsements
block only their PR; untrusted marker comments cannot select verification inputs.
Existing required checks retain their names. No paid model call or new credential
is authorized. Deployment stays blocked until independently reviewed protected
source, restricted context and authenticated live artifact acceptance are proved.
