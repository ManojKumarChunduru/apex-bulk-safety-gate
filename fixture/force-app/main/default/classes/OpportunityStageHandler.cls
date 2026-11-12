public with sharing class OpportunityStageHandler {
    // Why this exists: recalculates line totals when a stage changes. The child query sits
    // inside the loop over the batch, so it runs once per opportunity.
    public static void recalculate(List<Opportunity> opps, Map<Id, Opportunity> oldMap) {
        for (Opportunity o : opps) {
            Opportunity previous = oldMap.get(o.Id);
            if (o.StageName == previous.StageName) {
                continue;
            }
            Decimal total = 0;
            for (OpportunityLineItem li : [
                SELECT TotalPrice FROM OpportunityLineItem WHERE OpportunityId = :o.Id
            ]) {
                total += li.TotalPrice;
            }
            StageHistoryWriter.record(o.Id, previous.StageName, o.StageName, total);
        }
    }
}
