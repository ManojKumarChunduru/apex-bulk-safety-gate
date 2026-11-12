@IsTest
private class LeadTriggerTest {
    @IsTest
    static void routesOneLead() {
        Lead l = new Lead(LastName = 'Prospect', Company = 'Initech', Country = 'US');
        Test.startTest();
        insert l;
        Test.stopTest();
        System.assertNotEquals(null, [SELECT OwnerId FROM Lead WHERE Id = :l.Id].OwnerId);
    }
}
