public with sharing class RegionLookup {
    // Why this exists: a pure mapping, so a call to it from a loop costs nothing.
    private static final Map<String, String> REGIONS = new Map<String, String>{
        'US' => 'AMER', 'CA' => 'AMER', 'GB' => 'EMEA', 'DE' => 'EMEA', 'IN' => 'APAC'
    };
    public static String forCountry(String country) {
        if (country == null) {
            return 'UNKNOWN';
        }
        String region = REGIONS.get(country.toUpperCase());
        return region == null ? 'UNKNOWN' : region;
    }
}
