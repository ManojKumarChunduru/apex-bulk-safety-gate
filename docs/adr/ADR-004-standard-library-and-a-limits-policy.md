# ADR-004: Standard library only, argparse, and limits in a policy file with the reason beside each

Status: accepted.

## Context

The gate's job is a step in someone else's pipeline, after `sf apex run test` and before the
deploy. The runner for that pipeline has Python because the CLI tooling around Salesforce uses
it, and it rarely has a `pip install` step a team wants to maintain. The deployment target is
therefore "a directory and a Python interpreter".

## Decision

No runtime dependencies. `argparse` for the command line, `json`, `csv` and `xml.etree` for the
inputs, a hand-written tokenizer for Apex. The optional extras (`pytest`, `ruff`, `coverage` for
development; `playwright` and `cmarkgfm` for evidence) are never imported on the runtime path,
and the CI workflow installs the package with no extras and runs the gate to prove it.

The limits live in `src/absg/limits.py` as a policy: each entry has the documented synchronous
and asynchronous value, the unit, and the reason it is in the table. `absg limits` prints the
policy; `--policy policy.json` overrides any value; `--context async` switches to the
asynchronous column; an unknown limit name or a non-positive value is refused with exit 3 and the
offending key named. The three record counts the arithmetic depends on (chunk size 200, horizon
10,000, verdict at 200 records) are in the same table with the same treatment, because they are
the numbers an auditor asks about.

## The alternatives

`click` plus `rich` for a friendlier CLI. Rejected because the output is read by a pipeline and
occasionally by a human in a job summary; a markdown renderer in the gate itself covers the
second, and the first needs exit codes, not colours.

Hardcoding the limits as constants. Rejected on the first audit of a sibling project, where a
severity table was a constant in code and the auditor asked how a team with a sandbox at raised
limits would use it. A policy with a reason per line answers that and documents the numbers at
the same time.

A PMD ruleset. PMD runs on a JVM, which the target runner may not have, and its loop rule is a
line-level check that cannot tell a loop over three constants from a loop over trigger records
(ADR-001). The gate is not a replacement for PMD's other rules; it is the one check PMD cannot do.

## A note on GitHub rendering

The README's architecture diagram is a committed SVG rendered by `tools/render_architecture.py`,
not a live Mermaid fence, because GitHub's lazily loaded renderer has failed on valid diagrams in
sibling projects and there is no fix available from the repository side. The source stays
beneath the image in a fence labelled `mermaid-source` so nothing tries to render it.

## Consequences

- One file to drop into a step: `python -m pip install git+...` then `absg gate`.
- `absg limits` is the first demo segment, because the policy is the thing the whole gate
  compares against and it should be seen before any verdict.
- The policy is a single point of truth for the four limits (100 SOQL queries, 20 SOSL queries,
  150 DML statements, 10,000 DML rows), and the receipts check reads the values from it rather
  than from the prose.
