# ADR-005: What a committed fixture cannot establish

Status: accepted. This is the boundary of the repository, written down so that nobody has to
infer it.

## Context

Every figure in this repository is reproduced offline from a committed SFDX project. That is what
makes the figures reproducible, and it is also what keeps some of them declared rather than
observed. No org was used in the build; the Salesforce CLI was not available in the build
environment; nothing was compiled or deployed.

## Declared inputs, each with the experiment that would settle it

1. **The breach point.** That the 101st SOQL query in a synchronous transaction throws
   `System.LimitException` is taken from the documented limit of 100 SOQL queries (200 for
   asynchronous). The gate has never watched it happen. Experiment: deploy the fixture to a free
   Developer Edition org, run `AccountTriggersTest.insertsOneHundredAccounts` with the loop bound
   raised to 101, and record the exception. Then do the same for the DML statements breach at
   151 in `ContactEmailTrigger`. This is the single most valuable thing the repository could
   gain, and it is the first thing a Salesforce interviewer will ask for.
2. **Chunk sharing above 200 records.** The documentation says triggers execute on batches of 200
   and that limits are per transaction. The gate's `--records` arithmetic above 200 assumes the
   chunks of one DML share one transaction's limits, so that `OrderTotalTrigger` at 3 queries per
   invocation breaches at 6,601 records. Experiment: a Bulk API job of 6,601 `Order__c` updates
   in one batch, with the trigger's debug log showing `Limits.getQueries()` at the last chunk.
3. **The coverage report.** `fixture/coverage/test-result-codecoverage.json` is hand-written in
   the shape that `sf apex run test --code-coverage --output-dir` writes, as far as the shape
   could be verified from documentation during the build: a list of entries with `name`,
   `totalLines`, `lines`, `totalCovered` and `coveredPercent`. The loader validates that shape at
   the boundary. Experiment: run the fixture's tests in the org with `--code-coverage` and feed the
   produced file to the gate; the join is by trigger name and should need no change.
4. **The tests pass.** The fixture declares that its 12 Apex test methods pass, which is what makes
   100% coverage declarable for the breaching triggers: every one of them is tested below its
   breach size, so every test would pass in an org. The 100-record Account test stops 1 record
   short of the chain breach at 101. Experiment: the same org run as item 3.
5. **The fixture's Apex compiles.** It was written to compile and has not been. Field names such as
   `Duplicate_Of__c`, `Tier__c`, `Region__c`, `Escalation_Owner__c` and the custom objects
   `Order__c`, `Order_Line__c`, `Routing_Setting__c` and `Territory_Rule__c` would need their
   metadata in the org.

## Claims the fixture establishes the same way an org would

The arithmetic itself: given a per-invocation cost and a limit, the breach size is a property of
two integers, and it is the same on a laptop and in an org. The provenance reading: whether a
query sits inside a loop over trigger records is a property of the source, identical in any
environment. The chain composition: which triggers a DML on `Task` invokes is a property of the
project's trigger declarations.

## Excluded on purpose

- **CPU time**, 10,000 ms synchronous. It is a duration, it moves with the machine, and nothing in
  this repository publishes one.
- **Query rows**, the 50,000-row limit. It depends on how many rows the data has, which the
  source cannot say. A future version could bound it for `LIMIT n` queries and aggregate queries,
  which is also v2 work.
- **Heap**, callouts, future calls, queueable jobs. Out of scope for a trigger gate; the async
  sites are recorded so `absg explain` shows them.

## The fixture is the author's

The planted ground truth was written from the source before the gate ran, and the gate recovers
7 planted breaches with 0 false positives and 0 false negatives. That is a check on parsing and
arithmetic, not on what the gate would find in a codebase it has never seen. A measured zero is
below one in 7, and a second fixture by another author is the second item on the v2 list.
