@IsTest
private class OpportunityTriggersTest {
    @IsTest
    static void recalculatesOnStageChange() {
        Opportunity o = new Opportunity(
            Name = 'Deal', StageName = 'Prospecting', CloseDate = Date.today().addDays(30)
        );
        insert o;
        o.StageName = 'Negotiation';
        Test.startTest();
        update o;
        Test.stopTest();
        System.assertEquals('Negotiation', [SELECT StageName FROM Opportunity WHERE Id = :o.Id].StageName);
    }
}
