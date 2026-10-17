# Resumed repairs and acceptance, 2026-10-17

## Scope

Public candidate `5db330f771e4b1d2f813a88e887185d58199ec10` has the same
tree `87193e8519bd1bb19fa5d99a0e959dc53afcaaa2` as local tested commit
`97228a73b90e7db73533af7e07a8f5a7e8fb0716`.

Four bounded repairs were implemented with inert/offscreen reproduction:

- `KeyboardControlBridge.release_all`: reset/publication failure no longer skips
  independent neutral attempts; preserve first exception and successful return.
- Lock cleanup: nested cleanup cannot release the outer input-blocking owner.
- Controller-angle admission: ordinary start exceptions do not retain a phantom
  worker; rejected predecessors cannot erase a reentrantly admitted successor.
- Preferences: reject newly introduced physical control/module key collisions.

Independent reviewers checked the specific patches and focused tests. Their
results are narrow and do not qualify physical neutral delivery or the project.

## Complete candidate result: rejected

The selected offline profile completed with **327 PASS / 12 SKIP /
4 INCOMPLETE / 2 FAIL**, aggregate **NO-GO**. Both failures are settings binding
compatibility regressions:

- `test_binding_restore_quality`: saved swap/cycle and new-window restoration.
- `test_configuration_transactions`: whole binding-map canonicalization.

The initial collision guard incorrectly classified relocation of an already
shared physical key between control slots as a new collision. A correction must
preserve both original tests unchanged. A later green run cannot replace this
candidate's failed result.

All 678 declared verification input files retained start/end SHA-256
`e2edb124e3c58c4ce3e04e170fdc012bced6748d5267232a59df707440a67866`.
Documentation is outside this fingerprint. Raw logs are retained locally and
are not newly published here.

## Architecture close-out

- [RobotState authority ledger](robot_state_authority_audit_20261017.md): all
  242 declared fields inventoried, with bounded static references and explicit
  unresolved fields. This is not runtime semantic coverage.
- [Early resource ledger](window_early_resource_audit_20261017.md): acquisition,
  publication and cleanup boundaries, including untested early failure prefixes.
- [Principle acceptance](clean_code_principle_acceptance_20261017.md): the supplied
  Clean Code chapters mapped to concrete evidence and remaining gaps.
- [Evidence storage](evidence_storage_audit_20261017.md): lossless preservation
  plan; no bulk evidence removal or archive migration has occurred.

## Unresolved historical and external evidence

The historical 30-second activation timeout has a retained parent traceback but
no original child stack/output that locates the stall. Current diagnostics and
later passes do not establish causation.

The recorded DT7 22.028550 ms observation exceeded the unchanged 20 ms limit.
The original referenced local raw output is unavailable; later isolated passing
measurements do not explain it. Scheduling/contended caller work remain
hypotheses, not confirmed causes.

The four incomplete checks require the external team CRC reference, firmware
tree/host reference and installation preconditions. Native Windows, GPU, real
audio/video/serial and portable-package qualification remain external. Recorded
offscreen evidence is Linux; it must not be presented as Windows acceptance.
