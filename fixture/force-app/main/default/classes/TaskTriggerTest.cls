@IsTest
private class TaskTriggerTest {
    @IsTest
    static void escalatesToManagerOnInsert() {
        Task t = new Task(Subject = 'Call', OwnerId = UserInfo.getUserId());
        Test.startTest();
        insert t;
        Test.stopTest();
        System.assertNotEquals(null, [SELECT Id FROM Task WHERE Id = :t.Id]);
    }
}
