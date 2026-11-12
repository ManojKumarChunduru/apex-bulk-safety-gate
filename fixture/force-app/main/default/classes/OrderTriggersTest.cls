@IsTest
private class OrderTriggersTest {
    @IsTest
    static void rollsUpLinesFromStaticResource() {
        Order__c order = new Order__c(Name = 'Bulk order');
        insert order;
        Test.startTest();
        List<SObject> lines = Test.loadData(Order_Line__c.sObjectType, 'OrderLines');
        Test.stopTest();
        System.assertEquals(50, lines.size());
    }

    @IsTest
    static void countsOpenLinesOnUpdate() {
        Order__c order = new Order__c(Name = 'Single order');
        insert order;
        order.Status__c = 'Open';
        Test.startTest();
        update order;
        Test.stopTest();
        System.assertEquals(0, [SELECT Open_Line_Count__c FROM Order__c WHERE Id = :order.Id].Open_Line_Count__c);
    }
}
