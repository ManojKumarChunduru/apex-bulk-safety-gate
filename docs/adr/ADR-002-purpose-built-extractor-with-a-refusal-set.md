# ADR-002: A purpose-built reader with a stated refusal set, not a full parser and not an org

Status: accepted.

## Context

The cost of a trigger depends on a small part of Apex: braces, loop headers, SOQL and SOSL
brackets, DML keywords, `Database.*` calls, method calls into classes in the project, variable
declarations that say what a collection holds, and static Boolean guards. The rest of the
language (expressions, operators, string methods, type casts, exception classes) does not change
how many queries run.

## Decision

`src/absg/apex.py` tokenizes Apex with SOQL and SOSL brackets folded into single tokens and reads
class and trigger declarations. `src/absg/cost.py` walks bodies statement by statement and
charges each site by the multiplier of the loops around it. It is not a parser: it does not build
a syntax tree and it does not validate the program.

The price is paid in one direction only. Any construct the reader cannot bound is a refusal with
a reason from a closed vocabulary, and a trigger with a refusal is undecidable:

| Reason | Construct | Why it cannot be costed from source |
| --- | --- | --- |
| `dynamic_dispatch` | `Type.forName(...)` | the class that runs is chosen at runtime |
| `external_namespace` | `ns.Class.method(...)`, or a two-segment call on a class not in the project | the source is not here |
| `unbounded_loop` | a cost inside a loop over a query result, a method's return value, a `while`, or a counted loop with no literal or `.size()` bound | the iteration count depends on data |
| `unknown_target` | a DML whose target the reader cannot type | the object, and so the chain, is unknown |
| `unbounded_rows` | a DML on a query result or an untraceable collection | the row count depends on data |
| `recursion` | a method that reaches itself | the depth depends on data |
| `reentrant` | a DML on the trigger's own object with no static guard read in an `if` | the chain returns to itself |

What the reader accepts without refusing: loops over `Trigger.new`, `Trigger.old`, their maps
and anything assigned or grown from them; literal collections and counted loops with a literal
bound; `.size()` of a bounded collection as a loop bound; static and instance calls into classes
in the project, with the argument's provenance carried into the parameter; `this.method()` and
bare calls within a class; `Database.query`, `countQuery` and `getQueryLocator` as queries;
`Search.query` as a search; `Database.insert` and the other DML forms, and `EventBus.publish`, as
DML statements; `Test.loadData` with a literal resource name, resolved to the committed CSV's row
count; a static Boolean of a project class read in an `if` as a guard.

Platform calls (`System`, `String`, `Math`, `Schema`, an sObject's static methods, a custom
setting's `getInstance()`) are accepted at zero cost and recorded as sites, so `absg explain`
shows them. This is the one place the reader assumes rather than refuses, and it is stated here
because an auditor should know it.

## The alternatives

A full Apex parser. Rejected because it is weeks of work, almost all of it on constructs that do
not change the answer, and because it would still not say what `Type.forName` loads.

Running the trigger at 200 records in a scratch org. This is the real measurement and the
Pivot's trigger condition; it needs an org, and ADR-005 says exactly which claims it would turn
from declared into observed. The static reader exists because the question has to be asked in a
pull request, before an org has the change.

## Consequences

- 3 of 13 triggers undecidable on the fixture, and the README leads with that number.
- Conditional branches are costed as a sum: an `if` and its `else` that both issue a query are
  charged twice. This overcounts and is listed as v2 work.
- The reader's output is deterministic and independent of hash seed and thread count, which the
  suite checks by running the fixture twice.
- Two bugs found while building it are in the README's war stories: the `.add()` growth that was
  skipped because `.add()` is also a call, and the static field read as a foreign namespace.
