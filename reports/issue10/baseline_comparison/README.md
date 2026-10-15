# Issue 10 independent baseline differential

Baseline: clean `git archive` export of `bd2e590b43b9cfecef61b09f0577a2ba0181578e`.
Comparison target: the Issue 10 working tree during validation, before task-local dependency installation.
Each command used the same Python interpreter, an isolated temporary user-data directory, offscreen Qt mode, disabled camera/media preload, and a 30-second timeout. No hardware, dependency installation, or firmware mutation was performed by this comparison.

## Aggregate result retained

The original aggregate is **NO-GO: 33 PASS, 21 FAIL, 15 INCOMPLETE / 69 checks**. Baseline reproduction does not turn blocked checks into passes.

| Check/group | Baseline | Issue 10 tree | Verified cause |
|---|---|---|---|
| 18 GUI/HUD/startup suites | exit 1 | exit 1 | Missing PySide6 |
| API freeze | exit 1 | exit 1 | Missing PySide6; API comparison never ran |
| DT7 C-route review pitfalls | exit 1 | exit 1 | Missing PySide6 at the section 6 UI import; earlier sections ran |
| Referee integration | exit 1 | exit 1 | Same MQTT subscription assertion; direct backend probe confirms missing paho and no started client |
| Backend protocol | exit 77 | exit 77 | 189 checks pass, 3 video cases skipped because cv2 is absent |
| Polar wire protocol | exit 0 with skip | exit 0 with same skip | Optional third-party CRC reference script absent; aggregate correctly reports INCOMPLETE |

All **21 FAIL checks** were rerun on both trees. Every pair has the same exit status and terminal failure. Paired logs and exact findings are in `summary.json` and the adjacent `.baseline.txt` / `.current.txt` files.

The other 13 INCOMPLETE aggregate entries identify missing prepared firmware fixtures, vendor dumps, or read-only exclusion of a mutating legacy test. This comparison did not rerun those 13 entries and does not claim they passed.

## Conclusion and limits

No new Issue 10-caused failure was observed in the compared checks. GUI/API/MQTT behavior remains unverified in this initial interpreter because execution stops at missing dependencies. A task-local dependency-enabled rerun is still needed and is pending user approval; no alternate installation or dependency workaround was used. Retain this original evidence separately from any later rerun. Physical serial, official player-end delivery, ARM firmware build, and robot/mechanical safety are separate unverified gates.
