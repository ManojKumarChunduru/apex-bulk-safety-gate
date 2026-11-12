public with sharing class StageHistoryWriter {
    // Why this exists: keeps the history write out of the handler so it can be swapped for a
    // platform event later. It issues no query and no DML today.
    public static void record(Id oppId, String fromStage, String toStage, Decimal total) {
        System.debug(LoggingLevel.INFO, oppId + ': ' + fromStage + ' -> ' + toStage + ' (' + total + ')');
    }
}
