# Referee stage receipt freshness

The official RM2026 V1.3.1 protocol lists GameStatus at 5 Hz. It does not specify
this client's deadman deadline. The **1.0 second default is a conservative local
safety policy**, not a vendor timing guarantee or a field qualification result.
Reference: https://bbs.robomaster.com/wiki/20204847/804784?source=7

`OfficialSafety(stage_timeout_s=...)` and `configure_stage_timeout(...)` accept a
finite positive number of seconds. Changes require local review and field
qualification; do not increase the deadline to hide missing GameStatus traffic.

- Only a current-session, non-retained, successfully decoded GameStatus containing
  `current_stage` establishes stage evidence, at the original monotonic callback
  receipt time. Partial messages, model labels, and delayed HUD application do not.
- Stage and receipt time form one immutable observation. Unknown, expired,
  nonfinite or future-clock evidence cannot satisfy the fighting-stage gate.
- Owner polling expires evidence and locks armed control, clearing pending input.
  A new phase arriving after a gap also revokes the prior arm even if the owner
  has not polled. Paho callbacks defer observer delivery to the owner thread.
- Fresh traffic after expiry does not resume movement: the operator must explicitly
  re-arm with existing qualification requirements. A command delayed after initial
  admission is checked again immediately before Paho enqueue.
- Existing fixed-zero emergency release and token-bound supervised qualification
  remain separate. Stage expiry never releases E-stop. V2 live economy commands
  retain their additional current WireSnapshot and MATCH checks.

These changes do not establish receiver hardware operation, network reliability,
robot identity authentication, or field qualification. Mock diagnostics remain mock.
