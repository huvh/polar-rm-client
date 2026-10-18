# Retire stale inference input across image-source handoffs

An already-admitted webcam callback could outlive a source switch and overwrite current UDP/Native inference input. An entry-only source check also fails when the switch occurs during the destination's unlocked image copy. Actual-method controlled proofs reproduce both races without camera/network/model execution.

LocalAlignedVision now owns a separate input generation. Input commit and inference-result publication validate it; source-dependent history resets on the worker when the input changes. Model/worker lifetime epoch remains unchanged. UI adapters synchronize actual source/capture-session handoffs, validate frame identity/provenance, and retain same-source late owner adoption. No GUI/camera lock spans copying, inference or arbitrary callbacks. Existing public signatures stay unchanged; new owner ports are private.

Accepted source hashes: UI c9125375eacf224b45cf902cfcad92e22c940cdf597eec66863a3b960f54bdbe; owner 533ad7c77896449292f4ae5ad6109350b2676bc094c9f6c4015390b0673a4c7a. New tests: UI4be4ac78fa71d27991b3087a684258c6f7afd1721637f42f4fc4cad0acb0f3ea, owner216b9609f6307baa0f65530face279358bd35cc3bb479493fcecf6583d4af0a9.

Independent external and integrated validation: 40 new focused methods and seven extra controls pass. Original three camera proofs and four unchanged stop tests pass. Saved baseline UI26 reproduces 19 assertion/subtest failures, zero errors. Fourteen author and five independent omission mutants reject without errors. These overlapping selections are not additive unique coverage. New owner API tests are not claimed to run on the old API.

Three old test interception sites now observe the private token-bound port with assertions retained. One old mixed UDP-to-Synthetic plus owner-replacement characterization intentionally stops accepting stale input; separate positives preserve same-source replacement/startup. Heartbeat fixture adds only existing deployment/source-generation fields. Original test bytes are retained locally. Initial integrated normal-video run: 31 tests, one failure due to comparing an old in-submit snapshot with a new post-return snapshot. Only expected final frame_source was corrected to backend, preserving sequence4 and unchanged display publication. The failed fixture revision is retained; no production change was made for it.

Other retained counterevidence: an initial mutation escaped because Synthetic producer rejection masked a missing source-key check; final test adds a different-backend replacement. An early UI candidate reread Source unnecessarily; accepted version reuses existing observation. No existing assertion was broadly disabled. API freeze and static quality checks pass.

Boundaries: this protects inference input/results, not an atomic transaction over all display/timeline state. Registry writes are UI-owned; arbitrary external owner replacement plus nested ABA is not a generic supported protocol. Retired-input inference exceptions preserve existing worker error policy. No native pixels, hardware, real-time performance or field-cause claim.

Reproduce new modules: python -m unittest discover -s tests -p test_camera_input_handoff.py; python -m unittest discover -s tests -p test_local_vision_input_epoch.py

Full44's408/12/4/0 applies to earlier public92cd13f, not this repair. New aggregate pending; overall NO-GO remains for authentic external dependencies, separate installer qualification, Windows/device acceptance and historical timing causes. No raw logs published.

Corrected integrated normal-video neighbor:31 PASS; heartbeat neighbor:1 PASS. The initial focused failure above is not an aggregate failure.
