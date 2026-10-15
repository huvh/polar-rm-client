# Jello Esc menu

On the unobstructed main HUD, Esc opens a second-level Jello menu. Esc closes
it. Existing keybind capture, search/chat, student panels, Hero, Economy, and
ClickGUI keep their existing first refusal on Esc. Arrow keys or Tab select;
Enter/Space activates. Pointer activation requires press and release on the
same row, preventing stale HUD hotspots from receiving clicks.

- Continue: dismiss and keep held controls released.
- Return to startup: lock control through the existing backend lifecycle,
  neutralize inputs, return to scene selection. Never switch real output to mock.
- Exit client: confirmation with Cancel selected; final exit uses the existing
  lock/release/estop/shutdown closeEvent lifecycle.

The menu does not stop any timer, backend tick, or safety monitoring. Input
ownership is blocked at both event dispatch and the combat permission predicate.
F12 emergency stop remains available. Opening/closing neutralizes the existing
KeyboardControlBridge, including forced DT7/custom-controller release frames.

Rendering uses the existing unified GPU Jello 20px backdrop treatment and a
QPainter card on its interaction target, using the existing FontBook jello_light
asset and near-white Jello text. No new heavy resources are loaded. Emergency compatibility uses the same
card without CPU blur, framebuffer readback, or new per-frame image processing.
The MC/CS/BF6 HUD and Jello module list are unchanged. Base HUD refresh under this
menu is throttled to 4Hz while backend/safety updates retain their normal cadence.

## Verification

`QT_QPA_PLATFORM=offscreen python tests/test_escape_menu.py` exercises real Qt
input events on the production input/menu mixins, with inert hardware adapters.
It tests held controls and neutral frames with the real KeyboardControlBridge,
repeated Esc, modal precedence, input isolation, resize/hit testing, return lock,
exit confirmation, F12, and continued timer activity. This does not certify
physical robot safety or real driver/GPU behavior.

`python tests/test_escape_menu.py --preview` writes an actual offscreen QWidget
capture to `/tmp/polar-jello-menu-offscreen.png`. The image explicitly identifies
its inert background and lack of GPU blur; it is not a live hardware screenshot.

The offscreen capture verifies only emergency-card layout and input. It cannot
demonstrate the live Jello GPU backdrop, GPU compositing or hardware frame pacing;
those require a real OpenGL driver/display and remain unverified here.
