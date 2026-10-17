# Input cleanup failure isolation

Base: public `c22d9ba81d1d8cf975d85df03fb26412c313b524`. Recovery checkout was restored from GitHub; unavailable unpublished changes are not assumed recovered.

## Reproduced defects
Four deterministic offscreen/inert-output tests on the base produced three failures and one error:
- A failing local reset skipped both independent neutral egresses and pending-clear.
- A failing DT7 release skipped custom-controller release and pending-clear.
- A failed MQTT mock-output property lookup escaped modal cleanup before any reset or fail-closed latch.
- A synchronous output callback could inject W during the lock hook's cleanup.

## Change
The lock hook latches input blocking before cleanup, attempts independent actions separately, records every failure and rethrows the primary exception for the existing backend authority latch. Qualification and mouse capture are invalidated even when cleanup fails. A successful explicit cleanup clears the UI latch. Modal mode lookup is inside the guarded cleanup path; ordinary publication requires both valid mode and successful reset.

Focus-loss has its own independent fallback. The existing fixture now asserts exactly two neutral attempts and two pending clears on persistent reset failure (lock observer plus focus fallback); no authority checks were removed and no timeout was increased. The initial focused failure is retained locally.

## Verification
- New four-method regression: original source 3 FAIL / 1 ERROR; modified source 4 PASS.
- Eleven focused test files, 123 unittest methods: PASS (input cleanup, modal epoch, backend owner, backend lifecycle input failure, configuration quiescence, focus loss, tick contract, API contract, escape menu, keyboard characterization, emergency failures).
- Full offline regression: pending at this checkpoint.
- No independent reviewer, real robot, serial hardware, Windows/GPU or field qualification is claimed. Previous complete scores apply only to their original source commits.
- Raw logs remain local and are not included in this publication.
