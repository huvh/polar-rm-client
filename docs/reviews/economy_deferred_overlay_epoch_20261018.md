# Economy deferred overlay epoch repair

The existing close generation was checked before queuing the next overlay, but not when its queued callback ran. Reopening Economy between those points retired the old intent while the callback could still close the new session. The repair rechecks the existing generation at delivery with two lines; no new owner, public API or timing policy.

Baseline actual-method inert probes: 3 cases, 2 assertion failures, zero errors. New regression: 9 cases, 7 assertion/subtest failures on baseline, zero errors. Candidate independent focused selection: 25 PASS; original 3 PASS; 7 additional controls PASS. Seven independent mutations reject without errors. These overlapping selections must not be summed as unique coverage. Existing assertions unchanged. API freeze and static quality gate pass.

Source SHA256: 75be3a982a4d469d9399f45899827897ad870937128eb70abd3d029fb19747bc
Test SHA256: 2bce1ae1cefca220c412e4b66e37bcbeb188675b1a115fcaeb97b2727e12f052

The tests execute actual Economy/ClickGUI method AST and pure OverlayCoordinator with an inert timer queue. Independent controls also execute the Student adapter AST. This establishes ordering behavior, not native Qt delivery, rendering, device behavior or observed incidence. Same-generation competing modal policy, scheduling failures and process-control exceptions remain unchanged.

An initial author mutation-tool replacement changed both existing and new comparisons and caused errors; the corrected scoped tool and independent mutations reject by assertions. Initial counterevidence remains locally retained, not counted as accepted validation.

Reproduce: python -m unittest discover -s tests -p test_economy_deferred_overlay_epoch.py

Full41's 405 PASS / 12 SKIP / 4 INCOMPLETE / 0 FAIL applies to earlier public code 8b91d04ff5743368203a4463f06404d62a16296a, not this repair. A new aggregate is pending. Overall qualification remains NO-GO pending external dependencies, native Windows/device acceptance and unresolved historical timeout causes.
