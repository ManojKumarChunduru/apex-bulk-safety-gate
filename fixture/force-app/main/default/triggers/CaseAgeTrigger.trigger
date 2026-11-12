trigger CaseAgeTrigger on Case (after update) {
    // Updates its own object with no static guard: the chain returns to this trigger and
    // the gate cannot bound it.
    List<Case> aged = new List<Case>();
    for (Case c : Trigger.new) {
        aged.add(new Case(Id = c.Id, Age_Days__c = Date.today().daysBetween(c.CreatedDate.date())));
    }
    update aged;
}
