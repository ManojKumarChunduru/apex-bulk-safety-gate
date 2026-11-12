# ADR-003: Report the breach size, not a boolean at 200

Status: accepted.

## Context

Every bulkification checklist ends with the same instruction: write a test that inserts 200
records. A gate that returns pass or fail at 200 would match that instruction and would hide
three things the fixture contains.

## Decision

For every trigger and every limit with a non-zero cost, the gate computes the smallest record
count at which the cost exceeds the limit, up to a horizon of 10,000 records (one Bulk API
batch), and publishes it. The verdict at 200 records is derived from that number; the number is
the finding.

The arithmetic: the per-invocation cost is a polynomial in r. Records arrive in chunks of 200,
each chunk is one invocation, and the chunks share one transaction's limits, so the cost at R
records is the sum over chunks. The breach size is found by an exact scan upward, because the
horizon is small and the chunk boundary makes a closed form fiddly for no gain.

Every finding carries three more numbers: the largest record count any test exercised against
that trigger, the coverage percentage the report gave it, and whether the cost arrives through
a chain.

## What a boolean at 200 would hide

1. The constant-cost breach. `OrderTotalTrigger` costs 3 queries per invocation and is clean at
   200. At the 34th chunk the shared transaction has issued more than 100 queries, so it breaches
   at 6,601 records, inside one Bulk API batch. `OrderLineRollupTrigger` is the same shape through
   a chain, 4 queries per invocation, breaching at 5,001, the 26th chunk of a chain of two
   triggers. Both are correctly bulkified. A boolean
   calls both clean and a Data Loader job proves it wrong.
2. The resolution of the tests. "Clean at 200" says nothing about which record count the tests
   reached. `AccountTaskTrigger` is tested at 100 records and breaches at 101; the test passes
   and the gate says it is 1 record short.
3. The DML-rows horizon. A trigger that inserts one child per record has a breach size on the
   10,000 DML rows limit even when every other count is bounded; it is beyond the horizon in
   the fixture and the gate says so rather than saying clean.

## The alternative

A boolean at 200 with a `--strict` flag. Rejected because the information a team acts on is the
record count, not the flag: a breach at 101 is a bug to fix today, a breach at 6,601 is a limit
to document for the integration team, and the same boolean would cover both.

## Consequences

- `latent` is a third status between `breach` and `clean`: a breach within the horizon but above
  the configured record count. It does not fail the build (exit 0) unless `--records` is raised,
  which the CI workflow does once at 10,000 to show the arithmetic.
- The table has a row per trigger and a line per finding, and the markdown job summary carries
  both so the number is read where a human reads it.
- Measured by `experiments/exp03_resolution.py`: 7 breaches in all, 5 breaches at or below 200,
  2 breaches above 200.
