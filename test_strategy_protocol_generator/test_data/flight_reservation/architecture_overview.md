# Architecture: Northline Reservations payment and capacity flow

## System context

Travelers use the Northline web application. The web application calls the Booking API. The Booking API is the only component that changes booking state. It calls the Capacity service to reserve or release seats and the Payment adapter to start a card charge. The payment provider calls the Payment adapter, which publishes events onto the booking event bus.

Release 2.4 does not add a new database. Booking state is stored in the existing booking database. Seat counts are stored in the capacity database. Those two databases are updated by their own services.

## Components

- Web application: search, fare selection, payment form, and the payment-failed or confirmed result page.
- Booking API: creates pending bookings, applies payment events, and enforces the hold window.
- Capacity service: increments and decrements sellable seats for a flight fare. It rejects a reserve request that would make seats negative.
- Payment adapter: sends the charge request and verifies the provider signature on callbacks.
- Event bus: delivers PaymentCaptured and PaymentFailed. Delivery is at least once. Order is not guaranteed across different bookings. For one booking, consumers must still tolerate a duplicate of the same event.
- Idempotency store: keyed by payment_attempt_id. It records whether that attempt has already been applied.
- Notification service: sends email after a booking becomes confirmed. It is not called for payment failure.
- Support console: staff can view quarantined events. Staff cannot edit seat counts in release 2.4.

## Payment-failure sequence

1. The traveler selects a fare. Booking API creates a pending booking and calls Capacity service to reserve the seats.
2. The traveler submits card details. Payment adapter starts a charge with payment_attempt_id and the booking reference.
3. The provider reports failure. Payment adapter verifies the signature and publishes PaymentFailed.
4. Booking API loads the pending booking, checks the idempotency store, cancels the booking, and calls Capacity service to restore the reserved seats.
5. Booking API records the event identifier and the capacity change, then marks payment_attempt_id as applied.
6. A second delivery of the same PaymentFailed event finds the attempt already applied and makes no further booking or capacity change.

## States

A booking in this release is pending, confirmed, or cancelled. There is no refunded state. A pending booking can become confirmed or cancelled. A cancelled booking stays cancelled. A confirmed booking stays confirmed even if a late PaymentFailed event arrives; that event is quarantined.

## Failure behavior already specified

- If the capacity restore call fails, the booking stays pending, the event is retried, and no confirmation email is sent.
- If the booking was already cancelled by hold expiry, a later PaymentFailed event must not restore the seats again.
- Hold expiry and PaymentFailed can race. Only the first successful release may restore capacity.

## Deployment notes for testing

- Test environment uses a stub payment provider that can emit success, failure, duplicate failure, and a delayed failure.
- Test flights have a known starting seat count, normally 4 sellable seats, so a double restore is visible.
- Production card data is not available in the test environment. Use provider test cards only.
