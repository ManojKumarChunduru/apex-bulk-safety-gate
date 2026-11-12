public with sharing class RecursionGuard {
    // Why this exists: the static Boolean a trigger reads before re-entering itself. The
    // gate recognises a static Boolean read in an if condition as a guard (ADR-002).
    public static Boolean regionRan = false;
}
