trigger AccountDedupeTrigger on Account (before insert) {
    // Bulkified: one query for the whole batch, then a map lookup per record.
    Set<String> names = new Set<String>();
    for (Account a : Trigger.new) {
        names.add(a.Name);
    }
    Map<String, Id> existing = new Map<String, Id>();
    for (Account a : [SELECT Id, Name FROM Account WHERE Name IN :names]) {
        existing.put(a.Name, a.Id);
    }
    for (Account a : Trigger.new) {
        if (existing.containsKey(a.Name)) {
            a.Duplicate_Of__c = existing.get(a.Name);
        }
    }
}
