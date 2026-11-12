# ADR-001: Verdict by count provenance, not by line coverage

Status: accepted.

## Context

The deploy gate every Salesforce team already has is a coverage percentage: the org refuses a
deployment below 75% and a team policy often demands more. The question a governor limit asks
is different in kind. A SOQL query inside `for (Account a : Trigger.new)` is one line, covered
or not; the limit cares how many times that line runs, which is the record count of the
invocation. A one-record test covers the line. A 200-record test covers the same line. The
report reads 100% either way, and the breach is at the 101st record.

## Decision

The gate's verdict is computed from where a cost sits, never from whether a line was covered.
Every SOQL, SOSL and DML site is tagged with its loop provenance: once per transaction, once
per trigger record, once per element of a bounded constant, or unbounded. The cost of a trigger
is a polynomial in r, the record count of one invocation, and the breach size is the smallest
record count at which that polynomial, summed over chunks of 200, exceeds the limit.

The coverage report is read for one purpose: to place the coverage percentage next to the
breach size in the first table, so the two properties can be seen to be unrelated.

## The alternative, and why it was rejected

Trust the coverage report, perhaps with a higher floor. Rejected because no floor helps: a
100% floor is satisfied by one-record tests, and the fixture shows it. 4 of 11 fully covered
triggers breach at 200 records, and the tests behind them exercise at most 100 records.

A second alternative is PMD's rule that flags any query or DML inside a loop. It is a line-level
rule and so inherits the same blindness in the other direction: it flags the loop over three
constant statuses in `OrderTotalTrigger` (3 queries per invocation, clean at 200) as if it were
a loop over Trigger.new, and it cannot see the breach in `AccountTaskTrigger`, which contains no
query at all and breaches through the Task trigger it invokes.

## Consequences

- The verdict carries the tested size beside it, so a "clean" at N records is a claim about N
  records. The resolution of the tests is published, not implied.
- The gate needs the Apex source, not the org. That is also its limit: anything the source does
  not say (dynamic dispatch, a managed package, a data-dependent row count) is a refusal, and
  ADR-002 lists them.
- Measured by `experiments/exp02_coverage_vs_bulk.py` and `exp03_resolution.py`.
