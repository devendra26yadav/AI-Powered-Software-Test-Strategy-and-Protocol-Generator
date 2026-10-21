# Open questions for release 2.4

The following items are not decided in the requirements, architecture, user stories, event contract, or risk register. Testing should flag them instead of filling them in.

- OQ-001. The traveler-facing wording of the payment-failed message is not specified. FR-009 only requires that a payment-failed message is shown.
- OQ-002. No requirement defines how many times a failed capacity restore is retried, or how staff are alerted if retries stop.
- OQ-003. Processor timeout (failure code processor_timeout) may mean the provider is still deciding. The documents do not say whether Northline must wait before cancelling.
- OQ-004. No performance target is stated for search or for the confirmation email. NFR-001 applies only to applying one payment-failed event.
- OQ-005. No test execution records, defect counts, or approval signatures exist for release 2.4. Execution evidence is not available.
