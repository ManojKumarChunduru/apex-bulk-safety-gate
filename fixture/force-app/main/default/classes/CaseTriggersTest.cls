@IsTest
private class CaseTriggersTest {
    @IsTest
    static void escalatesTwoHundredCases() {
        List<Case> cases = new List<Case>();
        for (Integer i = 0; i < 200; i++) {
            cases.add(new Case(Subject = 'Bulk ' + i, Origin = 'Web'));
        }
        Test.startTest();
        insert cases;
        Test.stopTest();
        System.assertEquals(200, [SELECT COUNT() FROM Case WHERE Origin = 'Web']);
    }

    @IsTest
    static void agesOneCaseOnUpdate() {
        Case c = new Case(Subject = 'Single', Origin = 'Phone');
        insert c;
        c.Status = 'Working';
        Test.startTest();
        update c;
        Test.stopTest();
        System.assertEquals('Working', [SELECT Status FROM Case WHERE Id = :c.Id].Status);
    }
}
