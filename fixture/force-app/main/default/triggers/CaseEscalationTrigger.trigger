trigger CaseEscalationTrigger on Case (before insert) {
    // Bulkified: one query for the contacts of the whole batch.
    Set<Id> contactIds = new Set<Id>();
    for (Case c : Trigger.new) {
        if (c.ContactId != null) {
            contactIds.add(c.ContactId);
        }
    }
    Map<Id, Contact> contacts = new Map<Id, Contact>(
        [SELECT Id, Tier__c FROM Contact WHERE Id IN :contactIds]
    );
    for (Case c : Trigger.new) {
        Contact contact = contacts.get(c.ContactId);
        if (contact != null && contact.Tier__c == 'Platinum') {
            c.Priority = 'High';
        }
    }
}
