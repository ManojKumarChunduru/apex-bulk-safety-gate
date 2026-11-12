trigger AccountTaskTrigger on Account (after insert) {
    // One insert statement for the batch. The cost is in the Task trigger it invokes.
    AccountTaskHandler.createFollowUps(Trigger.new);
}
