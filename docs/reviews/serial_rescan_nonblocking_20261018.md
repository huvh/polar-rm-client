# Forward nonblocking serial discovery to angle ports

The UI rescan requests refresh_port_options(nonblocking=True), but its ControllerAngles branch omitted that keyword when calling port_choices. Actual method and helper execution with a held inert scanner reproduced flags [True, True, False]: an expired snapshot could synchronously scan on the callback thread despite an async successor already queued. This proves an avoidable blocking path, not the cause of historical field latency or a measured frame-rate gain.

The one-keyword repair forwards the caller's existing value. Blocking/default calls, configured angle options, discovery lifecycle and cache policies are retained; no new thread or device behavior is added.

Accepted source SHA256 f91a3e6d3af64f8199161c13ade344a26e6f06352d28564c591b5d96d5307c3f; corrected test SHA256 4428bbd7de02529cfe007f327a10b5082947e321cacafe1b010385580e901e80.

Independent corrected validation: 20 focused tests plus five extra controls PASS. New eleven baseline tests reproduce four assertion failures, zero errors; six mutations reject without errors. These overlapping selections must not be added as unique coverage. The old expected-blocking characterization intentionally fails on the repaired candidate and is retained as counterevidence.

Review caught a fixture gap before acceptance: initial idempotence tests mocked snapshots without guarding the real scan entry. Earlier author runs cannot establish whether physical enumeration occurred; their blanket pure-execution claim is withdrawn. Initial logs remain local. Corrected tests and runners use fail-closed scan boundaries and explicit inert collaborators; baseline, candidate and mutations were rerun. No native scanning or timing threshold is used for accepted defect proof. No original assertion was weakened and no raw logs are published.

Reproduce: python -m unittest discover -s tests -p test_serial_rescan_nonblocking.py

Full43's 407 PASS / 12 SKIP / 4 INCOMPLETE / 0 FAIL applies to previous public code7c5f611, not this newer repair. Aggregate qualification pending. Overall NO-GO remains: external references, disposable installer, native Windows/device acceptance and historical timeout causation are incomplete.

Integrated independent repository validation: 20 focused plus five controls PASS under an outer fail-closed physical-scan guard; exact hashes and sole-keyword source restoration verified. API/static checks pass.

## Completed full44 qualification

**408 PASS / 12 SKIP / 4 INCOMPLETE / 0 FAIL**, selected offline scope remains **NO-GO**. Run `e4a19ccd533c4624a37abdf3e985082a`; clean local code `d557e6aaecdbe46dfc97cbaf125b3b015df80be6`, public code `92cd13f3ce6b3a80472fb697b73bc962a1496a0f`, identical tree `c574082fa7f822b015b801927d322d66c6eb862f`.

All 763 declared inputs retained start/end SHA256 `b52054c8df5e93e5425f67287acc3b586be26d38c40b1dd2ccdb34e12f44f149`. New regression module passes eleven methods. Counts, clean source and input stability independently verified. These are suite/check counts, not unique methods or native performance evidence. This report-only follow-up changes no tested code.

The four incomplete checks still require authentic team CRC, complete firmware baseline, authentic vendor type dump and separate disposable legacy installer qualification. Native Windows/GPU/audio/video/serial/robot/portable acceptance and historical timeout causation remain open. Initial fixture-isolation gap and old blocking characterization remain disclosed above; historical failed/interrupted runs are retained. No raw logs published.
