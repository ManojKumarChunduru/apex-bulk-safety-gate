# The fixture

A real SFDX project: 13 triggers in the fixture over 8 objects, 8 handler and helper classes, 7
test classes with 12 Apex test methods, one 50-row CSV static resource, a declared coverage
report, and `EXPECTED_FINDINGS.json`, the ground truth written from the source before the gate
ran. Every count below is checked by `tools/check_numbers.py`.

Several objects carry more than one trigger. That is not best practice and it is common in the
wild; the gate treats every trigger on an object as invoked by a DML on it.

## What is planted, and where

| Trigger | Object | Shape | Carrier | Expected |
| --- | --- | --- | --- | --- |
| `AccountDedupeTrigger` | Account | bulkified, 1 query per invocation | `triggers/AccountDedupeTrigger.trigger` | clean within the horizon (breach at the 101st chunk, beyond it) |
| `AccountTaskTrigger` | Account | one insert for the batch, chain into Task | `classes/AccountTaskHandler.cls` | breach: r queries via chain, at 101 |
| `TaskAssignmentTrigger` | Task | query inside the loop over Trigger.new | `triggers/TaskAssignmentTrigger.trigger` | breach: SOQL at 101 |
| `ContactEmailTrigger` | Contact | insert inside the loop, chain into Case | `triggers/ContactEmailTrigger.trigger` | breach: DML statements at 151, SOQL via chain at 101 |
| `CaseEscalationTrigger` | Case | bulkified, 1 query per invocation | `triggers/CaseEscalationTrigger.trigger` | clean within the horizon |
| `OpportunityStageTrigger` | Opportunity | child query inside the loop, in a handler | `classes/OpportunityStageHandler.cls` | breach: SOQL at 101 |
| `OrderTotalTrigger` | Order__c | query inside a loop over three constants | `triggers/OrderTotalTrigger.trigger` | latent: 3 per invocation, breach at 6,601 |
| `OrderLineRollupTrigger` | Order_Line__c | bulkified, chain into Order__c | `classes/OrderLineRollupHandler.cls` | latent: 4 per invocation via chain, breach at 5,001 |
| `LeadRoutingTrigger` | Lead | handler chosen with Type.forName | `triggers/LeadRoutingTrigger.trigger` | undecidable: dynamic_dispatch |
| `OpportunitySyncTrigger` | Opportunity | handler in a managed package namespace | `triggers/OpportunitySyncTrigger.trigger` | undecidable: external_namespace |
| `AccountRegionTrigger` | Account | updates its own object behind a static guard | `triggers/AccountRegionTrigger.trigger` | clean: the chain stops at the guard |
| `ContactPhoneFormatTrigger` | Contact | field work only | `triggers/ContactPhoneFormatTrigger.trigger` | clean: no cost at any record count |
| `CaseAgeTrigger` | Case | updates its own object with no guard | `triggers/CaseAgeTrigger.trigger` | undecidable: reentrant |

Summary: 4 triggers breach at 200 records, 2 breach only above 200, 4 clean within the horizon,
3 of 13 triggers undecidable; 7 breaches in all, 3 breaches through a chain, 2 exist only through the
chain.

## The tests, and what they establish

The record count each test exercises is read from its source: `insert new Account()` is one, a
list filled by a counted loop is the loop bound, `Test.loadData` is the row count of the CSV.

| Test method | Object | Records | What it says about the triggers |
| --- | --- | --- | --- |
| `AccountTriggersTest.insertsOneAccount` | Account insert | 1 | covers both Account insert triggers at one record |
| `AccountTriggersTest.insertsOneHundredAccounts` | Account insert | 100 | `AccountTaskTrigger` is tested at 100 records and breaches at 101: it passes, 1 record short |
| `AccountTriggersTest.updatesRegionOnce` | Account update | 1 | the guarded re-entrant trigger at one record |
| `ContactTriggersTest.formatsPhonesInBulk` | Contact insert | 251 | the largest test anywhere exercises 251 records, on the trigger with no cost |
| `ContactTriggersTest.opensCaseWhenEmailChanges` | Contact update | 1 | `ContactEmailTrigger` at one record, 150 short of its DML breach |
| `OpportunityTriggersTest.recalculatesOnStageChange` | Opportunity update | 1 | all three Opportunity update triggers at one record |
| `OrderTriggersTest.rollsUpLinesFromStaticResource` | Order_Line__c insert | 50 | `Test.loadData` from `OrderLines.csv` |
| `OrderTriggersTest.countsOpenLinesOnUpdate` | Order__c update | 1 | `OrderTotalTrigger` at one record |
| `TaskTriggerTest.escalatesToManagerOnInsert` | Task insert | 1 | the direct SOQL breach at one record |
| `CaseTriggersTest.escalatesTwoHundredCases` | Case insert | 200 | the bulkified Case trigger at the conventional size |
| `CaseTriggersTest.agesOneCaseOnUpdate` | Case update | 1 | the unguarded re-entrant trigger at one record |
| `LeadTriggerTest.routesOneLead` | Lead insert | 1 | the dynamically dispatched trigger at one record |

8 of 12 Apex test methods exercise one record; 2 exercise 200 or more. Every test is below the
breach size of every trigger it fires, which is what makes it consistent to declare that they
all pass and that the breaching triggers are 100% covered.

## The declared coverage report

`coverage/test-result-codecoverage.json` is hand-written in the shape that
`sf apex run test --code-coverage --output-dir` produces. 11 triggers at 100%; `OrderTotalTrigger`
and `CaseAgeTrigger` at 75%. No CLI run produced this file; ADR-005 lists what an org run would
settle.

## What is not here

No org, no compiled Apex, no custom object metadata: the custom fields the triggers reference
(`Duplicate_Of__c`, `Tier__c`, `Region__c`, `Escalation_Owner__c`, `Open_Line_Count__c`,
`Age_Days__c`, `Total__c`, `Amount__c`, `Status__c`) and the custom objects (`Order__c`,
`Order_Line__c`, `Routing_Setting__c`, `Territory_Rule__c`) would need their metadata before the
project deployed. The gate does not read object metadata and does not need to.
