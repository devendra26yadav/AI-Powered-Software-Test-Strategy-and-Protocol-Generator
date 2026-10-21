# Product requirements: Northline Reservations, release 2.4

## Product

Northline Reservations is the passenger booking service for a regional airline. Travelers search flights, hold seats, pay by card, and receive a confirmation. Release 2.4 changes what happens when card payment fails after seats have been held.

## In scope

- Web booking for one adult passenger on a one-way or round-trip itinerary.
- Temporary seat hold, card payment, booking confirmation, and payment-failure cleanup.
- At-least-once delivery of payment events from the payment provider.

## Out of scope

- Multi-passenger bookings, group bookings, and unaccompanied minors.
- Partial payment, split tender, vouchers, and corporate accounts.
- Schedule changes, refunds after a successful ticket issue, and check-in.
- The airline's departure-control and crew systems.

## Actors

- Traveler: searches, holds, and pays.
- Booking API: creates the pending booking and applies payment outcomes.
- Capacity service: reserves and releases sellable seats.
- Payment adapter: talks to the card processor and publishes payment events.
- Notification service: sends the traveler email. SMS is not required in this release.

## Functional requirements

- FR-001. A traveler can search published flights by origin, destination, and date and see remaining sellable seats for each fare.
- FR-002. Selecting a fare creates a pending booking and reserves the requested seats. The reservation expires if payment is not completed within the hold window.
- FR-003. The traveler pays the displayed total by card. The amount charged must equal the total shown at hold time.
- FR-004. On a successful payment event, the pending booking becomes confirmed, the seat reservation becomes a sold seat, and the traveler receives one confirmation email containing the booking reference.
- FR-005. If payment fails, the system must cancel the pending booking, restore reserved capacity, and avoid duplicate cancellation during repeated event delivery.
- FR-006. A failed payment must not issue a ticket and must not send a confirmation email.
- FR-007. Repeating the same failed-payment event must leave the booking cancelled once and must not increase available seats a second time.
- FR-008. A payment event for an unknown booking reference is recorded and ignored. It must not change capacity.
- FR-009. After a failed payment, the traveler sees a payment-failed message and can start a new search. The cancelled booking reference cannot be paid again.
- FR-010. Every capacity change records the booking reference, the event identifier, the seat count, and the UTC time.

## Non-functional requirements

- NFR-001. Applying a payment-failed event, including capacity restore, completes within 5 seconds for a single booking under normal load.
- NFR-002. Payment event handling is safe when the same event is delivered more than once.
- NFR-003. Card numbers and card security codes are not stored by Northline Reservations. Only the payment-provider reference is stored.
- NFR-004. Booking and capacity records are encrypted in transit. Access to support tools requires an authenticated staff role.
- NFR-005. The booking pages work on the current versions of Chrome, Safari, Firefox, and Edge on a desktop browser.

## Business rules

- BR-001. The hold window is 15 minutes from the time the pending booking is created. This value is configured and is the same for every fare in release 2.4.
- BR-002. Available seats must not go below zero.
- BR-003. Restoring capacity adds back only the seats reserved for that pending booking.
- BR-004. A confirmation email is sent only after the booking state changes from pending to confirmed.
- BR-005. Payment events are processed in arrival order. A failed event that arrives after a successful confirmation for the same booking is quarantined for staff review and does not cancel the confirmed booking.

## Source identifiers

Use FR-001 through FR-010, NFR-001 through NFR-005, and BR-001 through BR-005 as the source requirement identifiers. Do not replace them with different meanings.
