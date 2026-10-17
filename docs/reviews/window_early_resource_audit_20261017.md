# Early window acquisition and failure-cleanup ledger

## Scope and result

Reviewed source: `97228a73b90e7db73533af7e07a8f5a7e8fb0716`, 2026-10-17.
This is a read-only production-source review plus a documentation addition. It
addresses gate C of `remaining_acceptance_checklist_20261017.md`; it does not
replace the accepted late-finalization or individual transport-owner reviews.

**The early-constructor ledger is now enumerated, but exhaustive failure cleanup
is not established.** No new resource-leak defect is asserted by this report.
There is no encompassing early-constructor abort boundary. The existing retained
abort starts at `polar_app.py:792`, after the services below have been assembled.
The outer application launcher calls `window_factory()` before its own try block
(`ui/polar/qt_application.py:87-89`), so it cannot recover the partial object when
that call raises. This is a source-proven boundary limitation, not a proof that
every earlier exception leaks an active resource.

Status terminology:
- **Source:** directly traced construction/publication behavior.
- **Tested:** a named check was executed in this review.
- **Gap:** failure-prefix or native lifetime behavior not established here.
- **External:** physical device/driver/codec/GL behavior requiring qualification.

## Ordered acquisition ledger

Line references below are to `rm_client/ui/polar_app.py` at the pinned source
unless another file is named. Pure scalar/container/UI-state initialization is
grouped; grouping does not assert that every constructor is incapable of raising.

| Order and publication | Acquisition and ownership traced | Failure/retirement boundary and evidence |
| --- | --- | --- |
| 475-486: Qt base, `_gpu_prewarm_timer` | `QOpenGLWidget` base exists first. `window_assembly.create_warmup_timer` creates a parent-owned single-shot QTimer and connects the callback without starting it. Pointer, tick, warmup state are Python owners. | Tested timer parent and inactive state in `test_window_assembly`. Partial-window native destruction after each widget-setting failure was not faulted. No GPU context initialization is established merely by these Python assignments. |
| 488-503: paths, registry, state, scenario/match/GUI managers | `prepare_runtime_paths` discovers paths, creates writable directories, then seeds default configuration. Subsequent objects establish model/policy state. | Path preparation ordering and failed-preparation suppression of seeding are tested. Filesystem effects already completed are not transactional rollback; this review does not require deleting user directories/defaults on constructor failure. Transitive state constructors are not exhaustively faulted. |
| 504: camera activation owner | `vision.CameraCaptureWorker.__init__:329-353` creates locks/events and sets `_thread=None`, without opening a camera. `CameraActivation` publishes that worker through the facade. | Source-traced inert construction. Normal shutdown tasks include camera close at 3265. Early failure after publication has no retained-abort guarantee. Actual capture acquisition belongs to later `start`, outside this row. |
| 506-514: backend, lifecycle, aliases | `backend/manager.py:103-215` constructs safety, MQTT/video/serial/angle/POLAR services, decoder and logger metadata; publishes `WindowLifecycleController` only after BackendManager returns. Decoder constructor has `_proc` and thread fields unset (`video_backend.py:746-791`); logger constructor has `_worker=None` (`backend/field_log.py:32-71`). `_apply_config` uses `set_active_video_source(..., start=False)`; fresh MQTT address changes start only when `_started` was already true. | Source-traced staged transport intent. This is not a complete transitive-constructor fault matrix or a claim that every nested library constructor is resource-free. An exception inside BackendManager occurs before `self.backend` is assigned. Existing native admission matrices remain separately scoped evidence. |
| 515-523: match observer, feedback, toggle listener | TopMatchBarController stores the window and renderer; backend stores its bound observer. `create_feedback_assets` constructs KillFxRenderer first, UiAudioManager second, and returns only after both succeed. Window then publishes `kill_fx` and `ui_audio`, then registry callback. `UiAudioManager` creates/migrates custom files, owns `ReliableAudioPool`, preloads sound effects and may preload media. Audio pool is a QObject with parent-owned devices/effects/media objects and application signal connections. KillSoundPool starts with `_executor=None` (`kill_audio.py:103-119`). | **Tested:** five `test_audio_pool_lifetime` cases, including failed later vision factory and successful close, prove the specific native-QObject retirement observations. They do not prove real codec/device retirement. Failure inside the feedback factory after the first service exists remains a distinct prefix from the tested later-factory failure. Production media preload can do more work than the explicit headless test path. |
| 532-548: compatibility pipeline, control, input hook, economy/config | Backend aliases, VideoPipeline, KeyboardControlBridge and sender callbacks establish references. The startup lock cleanup is invoked at 543 before later services exist. `ClientConfigStore` then creates its configuration directory (`config_store.py:58-60`). | Source establishes callback cycles and the early cleanup call. A failure at startup cleanup escapes before the abort region; it must not be equated with the later modal/lock failure-isolation guarantees. Exact retention of every callback cycle is untested here; a completed config-directory creation is a persistent filesystem effect. |
| 549-559: vision factory and publication | `window_assembly.create_vision_services` creates calibration and loads `polar_webcam` before constructing receiver, command cache, composite pipeline, local vision and bridge. Receiver/local/bridge constructors publish inert owners: no running threads, receiver socket unset, local detector unset. Factory result is then distributed into the window's selection owner and aliases. | Tested inert service fields and calibration-load failure preventing receiver construction. No fault at every later member construction/publication has been injected. Normal close enumerates local vision, receiver and bridge at 3266-3268. |
| 572-575: wallpaper and initial scenario/match application | `StartupWallpaperManager.__init__:743-776` creates package/image metadata, an inert VideoWallpaperPlayer, a ThreadPoolExecutor object, then ThumbnailDecoder. No thumbnail submission appears in that constructor. Scenario application updates registry and transport/control settings; `scenarios.py:162-179` calls MQTT address setter rather than a start API. | Tested wallpaper video thread unset and path wiring. Executor existence is an acquired service even before task admission; no prefix test here proves shutdown if ThumbnailDecoder or a later factory raises. Normal close separately drains video and thumbnail owners (3269-3270). Do not substitute active-thumbnail admission tests for this factory-prefix gap. |
| 576-591: presentation services | `create_presentation_services` loads fonts, creates shared animation/motion, cache and renderer/UI owners, then publishes the aggregate. `ui/fonts.py:29-60` registers discovered fonts with process-wide QFontDatabase; returned font IDs are not retained for removal. Asset images and other renderer internals were not individually lifetime-audited. | Tested animation sharing/instance separation, renderer initial state, and font-load failure suppressing later GPU-renderer construction. Process-wide font registration is an observable non-rolled-back side effect, not by itself an unintended leak. Repeated failed construction and internal renderer failure prefixes remain gaps. |
| 605-641: GPU facade services | `create_gpu_services` constructs renderer/compositor wrappers; actual allocation/shader initialization is deferred to the context owner. Window publishes individual aliases and CPU image/draw buffers. | Tested unavailable/uninitialized owners, no compositor background FBO, and distinct startup/HUD instances. Normal finalization releases named GPU owners under the GL context (3302-3317). Native allocation and partial native initialization are outside this early Python-factory result. |
| 642-783: remaining presentation/navigation state | Scalar/cache/image/layout state, navigation/timeline state, overlays, chat and notices. OverlayCoordinator retains the modal input callback. Frame scheduler exists, but the frame timer has not yet been created or started. | Source ordering. No exhaustive failure injection of this long state-initialization suffix. A failure here occurs after all preceding services, still before the retained-abort boundary. |
| 792-836: activation boundary, for comparison | Profile/presentation/scenario activation, shortcut installation, frame timer creation and start are within `except BaseException`, which invokes `_abort_failed_launch` and rethrows. | Existing accepted activation/finalization evidence applies here. It must not be extended backward to 475-791. `_begin_window_shutdown` eagerly refers to complete camera/vision/wallpaper/audio owners, so calling it on an arbitrary earlier prefix is not an established repair. |

## Executed checks

Interpreter: `../client-verification-venv/bin/python`; Qt offscreen; existing tests
explicitly disable local capture and media preload, use isolated temporary user
directories, and avoid physical device output.

- `python -m unittest discover -s tests -p test_window_assembly.py`: **12 PASS**.
- `python -m unittest discover -s tests -p test_audio_pool_lifetime.py`: **5 PASS**.

These 17 methods were rerun on the pinned source. They establish the specific
assertions listed above, not all acquisition failure prefixes. Qt reported
offscreen/audio-environment warnings; physical playback was not qualified. No
full profile, native Windows run, GL rendering or robot/serial test was performed
for this document.

## Bounded next evidence needed

1. Fault each aggregate factory and later publication boundary after the last
   successfully acquired owner. Record both Python weak-reference and valid
   native-QObject state, plus worker/process/socket/retained-handle ownership;
   do not use garbage-collection success alone as a native close certificate.
2. Separate failures *inside* feedback, backend, vision, wallpaper, presentation
   and GPU factories from failures after those factories return. In particular,
   test wallpaper executor acquisition followed by decoder-constructor failure,
   and first feedback-service success followed by second-service failure.
3. Preserve process-owned or persistent effects explicitly: font registrations,
   runtime directories, seeded configuration and migrated user sounds are not
   automatically window-owned disposable resources.
4. Use actual playback/decoder/device qualification separately for production
   media preload. The existing weak-callback regression closes its named
   QObject-retention defect only.

This ledger closes the documentation inventory gap. Exhaustive early-constructor
cleanup acceptance remains open until the bounded failure matrix supplies
evidence; no blanket rewrite or whole-client clearance follows from this audit.

## Follow-up: three bounded factory-prefix probes

Source `f457c6d222f25ba09d275eab557029d4bbe92492`, 2026-10-17. Added
`tests/test_early_window_factory_failures.py` and ran its three methods with
`../client-verification-venv/bin/python`: **3 PASS**. No production code was
changed for these probes. The original ledger above remains historical evidence;
this addendum narrows the following specific gaps.

1. **Feedback first service succeeds, second constructor rejects.** The actual
   KillFxRenderer and its real native SoundPool are constructed; UiAudioManager
   admission then raises. The original exception is preserved. After references
   unwind and Qt/GC events drain, the renderer weak reference has retired, no
   valid native pool remains, and its QObject `destroyed` signal was observed.
2. **Feedback failure inside the second service.** UiAudioManager constructs its
   real ReliableAudioPool, then injected preload failure raises. Both first and
   second native audio pools emit `destroyed` and neither remains valid after
   draining. This is stronger than a Python weak-reference-only observation.
3. **Wallpaper executor acquired before ThumbnailDecoder rejects.** The actual
   ThreadPoolExecutor and VideoWallpaperPlayer are constructed. The injected
   decoder-constructor failure occurs after executor publication. Its thread set
   is empty at acquisition and failure; no `threading.Thread.start` call occurs.
   Both owner weak references retire after unwind. No active native worker was
   acquired in this prefix, so absence of an explicit executor shutdown here did
   not reproduce an active-resource leak.

The tests use temporary user directories, empty assets, offscreen Qt, and the
existing media-preload/local-capture disabling settings. QMediaPlayer and
QSoundEffect source-loading/playback methods are patched. **Real QMediaDevices
construction can still initialize a platform multimedia service such as
PulseAudio.** Thus these tests do not claim that native multimedia initialization
is absent, nor qualify physical audio output, driver shutdown or real codec
cleanup. Source-loaded/preloaded production media remains outside these probes.

No actual retained-owner/resource-leak defect was reproduced in these three
prefixes. They narrow the feedback and idle-wallpaper factory gaps; they do not
discharge every early-constructor failure, an already-running executor failure,
or the production-media qualification still identified above.

Diagnostic follow-up at the same production source: the retained-native-object
assertion compares the observed count, avoiding repr of a rescued/deleted Qt
wrapper. The three methods pass again. Two in-process rejecting controls that
deliberately retain respectively the first feedback renderer and the wallpaper
executor each produce **one assertion failure, zero errors**. These controls
show the corresponding retirement assertions reject retention; they are not
production defects or extra qualification of native media.
