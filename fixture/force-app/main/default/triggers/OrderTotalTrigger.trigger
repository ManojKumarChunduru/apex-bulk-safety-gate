trigger OrderTotalTrigger on Order__c (before update) {
    // Looks like a query inside a loop; the loop is over three constant statuses, so it
    // costs three queries per invocation regardless of the record count.
    Set<Id> orderIds = Trigger.newMap.keySet();
    for (String status : new List<String>{'Draft', 'Open', 'Closed'}) {
        Integer count = [
            SELECT COUNT() FROM Order_Line__c WHERE Order__c IN :orderIds AND Status__c = :status
        ];
        for (Order__c o : Trigger.new) {
            if (status == 'Open') {
                o.Open_Line_Count__c = count;
            }
        }
    }
}
