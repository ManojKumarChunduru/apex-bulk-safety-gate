@IsTest
private class ContactTriggersTest {
    @IsTest
    static void formatsPhonesInBulk() {
        List<Contact> contacts = new List<Contact>();
        for (Integer i = 0; i < 251; i++) {
            contacts.add(new Contact(LastName = 'Bulk ' + i, Phone = '(555) 010-' + i));
        }
        Test.startTest();
        insert contacts;
        Test.stopTest();
        System.assertEquals(251, [SELECT COUNT() FROM Contact WHERE Phone LIKE '555010%']);
    }

    @IsTest
    static void opensCaseWhenEmailChanges() {
        Contact c = new Contact(LastName = 'Vance', Email = 'old@example.com');
        insert c;
        c.Email = 'new@example.com';
        Test.startTest();
        update c;
        Test.stopTest();
        System.assertEquals(1, [SELECT COUNT() FROM Case WHERE ContactId = :c.Id]);
    }
}
