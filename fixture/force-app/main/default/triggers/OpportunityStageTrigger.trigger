trigger OpportunityStageTrigger on Opportunity (after update) {
    OpportunityStageHandler.recalculate(Trigger.new, Trigger.oldMap);
}
