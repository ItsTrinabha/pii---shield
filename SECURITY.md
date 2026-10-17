# Security policy

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability or include real personal data in a report. Use GitHub's
private **Report a vulnerability** feature for this repository. Include a minimal synthetic reproduction, affected
version or commit, expected impact, and any suggested mitigation.

## Supported version

Security fixes are applied to the latest revision on the default branch. Cloak is a demonstration and research project,
not a compliance certification or a guarantee that all PII will be detected.

## Scope

High-priority reports include release-gate bypasses, raw-value exposure in logs or reports, unsafe archive/XML parsing,
network transmission of unsanitized content, seal bypasses, and redacted files that retain recoverable source values.
