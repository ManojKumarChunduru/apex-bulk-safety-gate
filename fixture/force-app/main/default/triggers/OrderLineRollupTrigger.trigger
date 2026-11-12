trigger OrderLineRollupTrigger on Order_Line__c (after insert, after update) {
    OrderLineRollupHandler.rollUp(Trigger.new);
}
