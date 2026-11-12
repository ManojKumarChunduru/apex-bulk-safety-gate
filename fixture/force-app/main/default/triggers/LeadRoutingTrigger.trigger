trigger LeadRoutingTrigger on Lead (before insert) {
    // The handler is chosen at runtime from a custom setting, so the source does not say
    // which class runs. The gate refuses to cost it rather than guessing.
    String handlerName = Routing_Setting__c.getInstance().Handler_Class__c;
    Type handlerType = Type.forName(handlerName);
    ILeadRouter router = (ILeadRouter) handlerType.newInstance();
    router.route(Trigger.new);
}
