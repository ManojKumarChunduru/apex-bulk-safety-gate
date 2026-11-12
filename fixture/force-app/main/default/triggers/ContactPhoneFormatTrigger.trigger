trigger ContactPhoneFormatTrigger on Contact (before insert, before update) {
    // Pure field work: no query, no DML, no cost at any record count.
    for (Contact c : Trigger.new) {
        if (c.Phone != null) {
            c.Phone = c.Phone.replaceAll('[^0-9+]', '');
        }
    }
}
