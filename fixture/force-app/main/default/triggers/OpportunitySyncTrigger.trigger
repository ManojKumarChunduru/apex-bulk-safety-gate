trigger OpportunitySyncTrigger on Opportunity (after update) {
    // Managed package handler: its source is not in this project.
    erp.SyncHandler.push(Trigger.new);
}
