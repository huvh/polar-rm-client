# Forward nonblocking serial discovery to angle ports

The UI rescan requests refresh_port_options(nonblocking=True), but its ControllerAngles branch omitted that keyword when calling port_choices. Actual method and helper execution with a held inert scanner reproduced flags [True, True, False]: an expired snapshot could synchronously scan on the callback thread despite an async successor already queued. This proves an avoidable blocking path, not the cause of historical field latency or a measured frame-rate gain.

The one-keyword repair forwards the caller's existing value. Blocking/default calls, configured angle options, discovery lifecycle and cache policies are retained; no new thread or device behavior is added.

Accepted source SHA256 f91a3e6d3af64f8199161c13ade344a26e6f06352d28564c591b5d96d5307c3f; corrected test SHA256 4428bbd7de02529cfe007f327a10b5082947e321cacafe1b010385580e901e80.

Independent corrected validation: 20 focused tests plus five extra controls PASS. New eleven baseline tests reproduce four assertion failures, zero errors; six mutations reject without errors. These overlapping selections must not be added as unique coverage. The old expected-blocking characterization intentionally fails on the repaired candidate and is retained as counterevidence.

Review caught a fixture gap before acceptance: initial idempotence tests mocked snapshots without guarding the real scan entry. Earlier author runs cannot establish whether physical enumeration occurred; their blanket pure-execution claim is withdrawn. Initial logs remain local. Corrected tests and runners use fail-closed scan boundaries and explicit inert collaborators; baseline, candidate and mutations were rerun. No native scanning or timing threshold is used for accepted defect proof. No original assertion was weakened and no raw logs are published.

Reproduce: python -m unittest discover -s tests -p test_serial_rescan_nonblocking.py

Full43's 407 PASS / 12 SKIP / 4 INCOMPLETE / 0 FAIL applies to previous public code7c5f611, not this newer repair. Aggregate qualification pending. Overall NO-GO remains: external references, disposable installer, native Windows/device acceptance and historical timeout causation are incomplete.

Integrated independent repository validation: 20 focused plus five controls PASS under an outer fail-closed physical-scan guard; exact hashes and sole-keyword source restoration verified. API/static checks pass.
