require ["variables", "envelope", "reject", "relational", "comparator-i;ascii-numeric"];
# The SMTP envelope has already been bound to the authenticated primary address.
# Reject multiple From headers AND multiple addresses within a single header.
if anyof (
    not header :count "eq" :comparator "i;ascii-numeric" "from" "1",
    not address :count "eq" :comparator "i;ascii-numeric" "from" "1",
    not address :is "from" "${envelope.from}"
) {
    reject "550 5.7.1 From must be your authenticated primary address";
    stop;
}
if exists "sender" {
    if anyof (
        not header :count "eq" :comparator "i;ascii-numeric" "sender" "1",
        not address :count "eq" :comparator "i;ascii-numeric" "sender" "1",
        not address :is "sender" "${envelope.from}"
    ) { reject "550 5.7.1 Sender must match From"; stop; }
}
if exists "reply-to" {
    if anyof (
        not header :count "eq" :comparator "i;ascii-numeric" "reply-to" "1",
        not address :count "eq" :comparator "i;ascii-numeric" "reply-to" "1",
        not address :is "reply-to" "${envelope.from}"
    ) { reject "550 5.7.1 Reply-To must match From"; stop; }
}
# Do not permit misleading forwarding/resending identities.
if exists ["resent-from", "resent-sender", "resent-to", "resent-cc", "resent-bcc"] {
    reject "550 5.7.1 Resent headers are disabled";
}
