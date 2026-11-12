@IsTest
private class AccountTriggersTest {
    @IsTest
    static void insertsOneAccount() {
        Account a = new Account(Name = 'Acme', BillingCountry = 'US');
        Test.startTest();
        insert a;
        Test.stopTest();
        System.assertEquals(1, [SELECT COUNT() FROM Task WHERE WhatId = :a.Id]);
    }

    @IsTest
    static void insertsOneHundredAccounts() {
        List<Account> accounts = new List<Account>();
        for (Integer i = 0; i < 100; i++) {
            accounts.add(new Account(Name = 'Bulk ' + i, BillingCountry = 'US'));
        }
        Test.startTest();
        insert accounts;
        Test.stopTest();
        System.assertEquals(100, [SELECT COUNT() FROM Task]);
    }

    @IsTest
    static void updatesRegionOnce() {
        Account a = new Account(Name = 'Globex', BillingCountry = 'DE');
        insert a;
        a.BillingCountry = 'IN';
        Test.startTest();
        update a;
        Test.stopTest();
        System.assertEquals('APAC', [SELECT Region__c FROM Account WHERE Id = :a.Id].Region__c);
    }
}
