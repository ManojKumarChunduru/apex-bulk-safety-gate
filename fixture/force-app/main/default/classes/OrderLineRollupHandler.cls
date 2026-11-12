public with sharing class OrderLineRollupHandler {
    // Why this exists: one aggregate query and one update for the batch. Bulkified, and still
    // not free: the update invokes OrderTotalTrigger, which costs three queries per invocation.
    public static void rollUp(List<Order_Line__c> lines) {
        Set<Id> orderIds = new Set<Id>();
        for (Order_Line__c line : lines) {
            orderIds.add(line.Order__c);
        }
        Map<Id, Decimal> totals = new Map<Id, Decimal>();
        for (AggregateResult ar : [
            SELECT Order__c oid, SUM(Amount__c) total FROM Order_Line__c
            WHERE Order__c IN :orderIds GROUP BY Order__c
        ]) {
            totals.put((Id) ar.get('oid'), (Decimal) ar.get('total'));
        }
        List<Order__c> updates = new List<Order__c>();
        for (Id orderId : orderIds) {
            updates.add(new Order__c(Id = orderId, Total__c = totals.get(orderId)));
        }
        update updates;
    }
}
