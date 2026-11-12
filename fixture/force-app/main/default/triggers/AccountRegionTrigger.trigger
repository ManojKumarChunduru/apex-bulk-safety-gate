trigger AccountRegionTrigger on Account (after update) {
    // Updates its own object, which re-enters this trigger; the static guard stops the
    // second pass, so the chain is bounded.
    if (!RecursionGuard.regionRan) {
        RecursionGuard.regionRan = true;
        List<Account> toUpdate = new List<Account>();
        for (Account a : Trigger.new) {
            toUpdate.add(new Account(Id = a.Id, Region__c = RegionLookup.forCountry(a.BillingCountry)));
        }
        update toUpdate;
    }
}
