trigger TaskAssignmentTrigger on Task (before insert) {
    // One query per task: the classic breach at the 101st record.
    for (Task t : Trigger.new) {
        User owner = [SELECT Id, ManagerId FROM User WHERE Id = :t.OwnerId];
        if (owner.ManagerId != null) {
            t.Escalation_Owner__c = owner.ManagerId;
        }
    }
}
