public with sharing class AccountTaskHandler {
    // Why this exists: the follow-up Task per new Account is created in one DML statement,
    // which is the bulkified shape. The limit it reaches is inside TaskAssignmentTrigger.
    public static void createFollowUps(List<Account> accounts) {
        List<Task> tasks = new List<Task>();
        for (Account a : accounts) {
            tasks.add(new Task(
                WhatId = a.Id,
                OwnerId = a.OwnerId,
                Subject = 'Welcome call',
                ActivityDate = Date.today().addDays(3)
            ));
        }
        insert tasks;
    }
}
