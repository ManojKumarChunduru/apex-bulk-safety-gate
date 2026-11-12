public with sharing class LeadRouter implements ILeadRouter {
    // Why this exists: the handler LeadRoutingTrigger resolves by name at runtime. It issues
    // one query per lead, which the gate cannot see through Type.forName.
    public void route(List<Lead> leads) {
        for (Lead l : leads) {
            List<Territory_Rule__c> rules = [
                SELECT OwnerId__c FROM Territory_Rule__c WHERE Country__c = :l.Country LIMIT 1
            ];
            if (!rules.isEmpty()) {
                l.OwnerId = rules[0].OwnerId__c;
            }
        }
    }
}
