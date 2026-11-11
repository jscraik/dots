# Security and Governance References

> Public library port. Read [migration scope](migration-scope.md) before using
> retained Configs commands or installation recipes. Source-specific
> checks remain Configs requirements; this candidate grants no activation.


## Table of Contents

- [How to use these references](#how-to-use-these-references)
- [Security and supply chain](#security-and-supply-chain)
- [AI systems](#ai-systems)

## How to use these references

Use the current primary publication that matches the task rather than treating
this page as a frozen version baseline. State the selected standard and the
specific control or risk it informs; do not claim compliance from a link alone.

## Security and supply chain

- [OWASP Top 10](https://owasp.org/www-project-top-ten/) for application risk.
- [OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/)
  for testable application-security controls.
- [NIST Secure Software Development Framework](https://csrc.nist.gov/projects/ssdf)
  for secure-development practices.
- [SLSA](https://slsa.dev/) and the [OpenSSF Baseline](https://baseline.openssf.org/)
  for build provenance and open-source supply-chain controls.
- [CycloneDX](https://cyclonedx.org/specification/overview/) for SBOM and VEX
  formats where the repository needs them.

## AI systems

- [OWASP Top 10 for LLM Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/)
  for application-level AI threats.
- [NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework) for risk
  management and governance.
- [MITRE ATLAS](https://atlas.mitre.org/) for adversarial ML and AI techniques.

Apply the least amount of governance that materially addresses the evidence;
the repository's executable contract remains the delivery authority.
