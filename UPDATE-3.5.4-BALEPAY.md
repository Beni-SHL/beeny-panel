# Beeny Panel 3.5.4 / BalePay Bridge 0.3.0

- Gateway configuration: `/payments/balepay` (English UI, under Payments navigation); old settings route remains compatible.
- WordPress checkout is Persian: connect bot, register order/send invoice, return and verify payment.
- Invoice title uses `سفارش شماره XXXXXXXX`, where XXXXXXXX is the first eight hexadecimal characters of the panel's UUID. This is a display number, not a sequential WooCommerce order number.
- Intended payment confirmation requires the separate WordPress bridge (not included or live-tested here): Bale `successful_payment`, inquiry, signed Beeny confirmation, idempotent renewal. Clicking verify never directly approves a renewal.
- Gateway enabled toggle blocks new orders; existing reconciliation continues.
- Back up panel DB and WordPress first. Install the panel zip with the project's normal update procedure; install the bridge zip in WordPress.
- Register the Bale webhook in WordPress settings after updating credentials. Verify on staging with test transactions, bot connection, invoice issuance, webhook, renewal and failure recovery before enabling production.
- Existing pending orders created with older bridge versions may need manual reconciliation.
