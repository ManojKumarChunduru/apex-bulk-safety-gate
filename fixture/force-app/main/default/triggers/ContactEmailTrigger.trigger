trigger ContactEmailTrigger on Contact (after update) {
    // One DML statement per changed contact, and each statement invokes the Case triggers.
    for (Contact c : Trigger.new) {
        Contact previous = Trigger.oldMap.get(c.Id);
        if (c.Email != previous.Email) {
            insert new Case(ContactId = c.Id, Subject = 'Email changed', Origin = 'Trigger');
        }
    }
}
