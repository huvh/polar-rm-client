# Reconstructed backend session and qualification admission

This is a new source reconstruction after loss of the prior temporary workspace.
It is not the lost 2700ada tree and does not inherit that tree's test results.

- Arming requires current SUBACK before reading signed evidence. The MQTT client,
  ClientId, receive generation and profile must remain the same after evidence
  verification and after arm notification. An observer revocation cannot report
  MATCH_ARMED success. Real publication still has its own final boundary.
- Core support asks the actual profile whether KMC and CustomControl are supported.
  A version constant, non-read-only flag or decoded V2 schema is insufficient.
- Hero deployment evidence remains signed and dynamically expiring but is separate
  from general core qualification. Only robot1/101 with its own test obtains Hero
  capability. No stored old signature is rewritten or granted a new role.
- Readiness reports the selected profile and protocol, not a universal V1.3.1 pass.
  All control transport gates require accepted current subscriptions. Only Hero
  roles require the Hero hardware gate for their core field candidate report.
- Referee freshness rejects future, nonfinite, nonnumeric, bool, nonpositive and
  arbitrarily large receipts; absence is never a fresh observation.

Fresh offline verification: test_backend_alignment_admission.py 12 methods PASS;
test_official_feed_receive_freshness.py 9 PASS; test_qualification_observations.py
10 PASS. These checks open no hardware and do not certify a real match.

## Reconstructed V2 economic and manager stage

Manager binds the actual state and QualificationManager owner into MQTT after
construction. Common, Sentry, Air and paid Map paths carry the confirmed immutable
snapshot without copying it. The final transport guard, not the UI, owns admission.
The early action gate rejects wrong role and Python value types before a codec
can coerce them. V2 Performance has explicit Aerial same-team Sentry mode versus
Hero/Infantry self-selection; V1 static mapping remains unchanged. Preparation
uses only explicit supervised core tokens, never implicit arming.

Fresh pure-rule13 and manager6 tests PASS. Common quantities, fixed remote package,
Engineer revival, per-field boolean/freshness, actual revival quote, same-team
Sentry intervention fee and unavailable target paid revival are covered. Sentry
fixed-price requests do not prove target readiness. No local fake ACK or inherited
five-second legacy transaction is created. Actual RMUC mode binding is required
at the transport and confirmation boundaries; it is not claimed as a wire field.
