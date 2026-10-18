#!/usr/bin/env python3
"""Install the audited six-joint controller contract into StandardRobot++ 2722e0d.

This is an offline source patch, not a flash tool. It changes no pin assignment,
robot profile, keyboard transport, or remote-control safety switch.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from file_guard import FileJournal, SnapshotError

MARK = "POLAR-CONTROLLER-ANGLE"
OWNED = (
    "application/referee/referee.c",
    "application/referee/referee.h",
    "application/mechanical_arm/mechanical_arm_engineer.c",
    "application/custom_controller/custom_controller_connect.c",
    "application/custom_controller/custom_controller_task.c",
)

DECLARATIONS = r'''
/* POLAR-CONTROLLER-ANGLE: 0x0302, six little-endian float32 joint radians.
 * The final six payload bytes are reserved. No data is valid at startup.
 * Exactly 300 ms old is stale. A fresh valid frame restores availability;
 * all existing DT7, mode, limit, and jump/error gates still apply.
 * GetCustomControllerAngles leaves output unchanged when unavailable. */
#define CUSTOM_CONTROLLER_ANGLE_COUNT 6U
#define CUSTOM_CONTROLLER_ANGLE_TIMEOUT_MS 300U
/* Pinned engineer-controller output limits, radians. These are the sender's
 * clamps, not universal robot geometry. Allow binary32 rounding at endpoints. */
#define CUSTOM_CONTROLLER_ANGLE_BOUND_EPSILON 0.00001f
extern bool GetCustomControllerOnline(void);
extern bool GetCustomControllerAngles(float angles[CUSTOM_CONTROLLER_ANGLE_COUNT]);
extern float GetCustomControllerPos(uint8_t index);
'''

IMPLEMENTATION = r'''
/* POLAR-CONTROLLER-ANGLE: independent angle mailbox, never referee liveness.
 * Validated A5 framing/CRC is the caller's responsibility, as for the existing
 * referee dispatcher. The short critical sections give the arm one coherent
 * six-axis sample and timestamp, including when RX is called from an IRQ. */
typedef char ControllerAngleFloatSizeCheck[(sizeof(float) == 4U) ? 1 : -1];
static const float controller_angle_min[CUSTOM_CONTROLLER_ANGLE_COUNT] = {
    -6.283185307179586f, -1.10f, -2.50f, -12.566370614359172f,
    -14.137166941154069f, -14.137166941154069f
};
static const float controller_angle_max[CUSTOM_CONTROLLER_ANGLE_COUNT] = {
    6.283185307179586f, 1.20f, 0.00f, 12.566370614359172f,
    14.137166941154069f, 14.137166941154069f
};
static float controller_angle_sample[CUSTOM_CONTROLLER_ANGLE_COUNT];
static uint32_t controller_angle_time;
static bool controller_angle_valid;

static void CustomControllerAnglesReset(void)
{
    uint32_t saved = __get_PRIMASK();
    __disable_irq();
    controller_angle_valid = false;
    controller_angle_time = 0U;
    memset(controller_angle_sample, 0, sizeof(controller_angle_sample));
    __set_PRIMASK(saved);
}

static bool CustomControllerAnglesAccept(const uint8_t *payload, uint16_t length)
{
    float sample[CUSTOM_CONTROLLER_ANGLE_COUNT];
    uint32_t i, bits, saved;
    if (payload == 0 || length != 30U) return false;
    for (i = 0U; i < CUSTOM_CONTROLLER_ANGLE_COUNT; ++i) {
        /* STM32's wire ABI is little-endian IEEE-754 binary32. Assemble the
         * bits explicitly; no unaligned float pointer or strict-aliasing cast. */
        const uint8_t *p = payload + 4U * i;
        bits = (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
               ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
        if ((bits & 0x7f800000U) == 0x7f800000U) return false;
        memcpy(&sample[i], &bits, sizeof(float));
        if (sample[i] < controller_angle_min[i] - CUSTOM_CONTROLLER_ANGLE_BOUND_EPSILON ||
            sample[i] > controller_angle_max[i] + CUSTOM_CONTROLLER_ANGLE_BOUND_EPSILON) return false;
    }
    saved = __get_PRIMASK();
    __disable_irq();
    memcpy(controller_angle_sample, sample, sizeof(sample));
    controller_angle_time = HAL_GetTick();
    controller_angle_valid = true;
    __set_PRIMASK(saved);
    return true;
}

bool GetCustomControllerAngles(float angles[CUSTOM_CONTROLLER_ANGLE_COUNT])
{
    bool ready;
    uint32_t saved = __get_PRIMASK();
    __disable_irq();
    ready = controller_angle_valid &&
        (uint32_t)(HAL_GetTick() - controller_angle_time) < CUSTOM_CONTROLLER_ANGLE_TIMEOUT_MS;
    /* Latch observed expiry so a later tick wrap cannot resurrect old data. */
    if (!ready) controller_angle_valid = false;
    if (ready && angles != 0) memcpy(angles, controller_angle_sample, sizeof(controller_angle_sample));
    __set_PRIMASK(saved);
    return ready;
}

bool GetCustomControllerOnline(void)
{
    return GetCustomControllerAngles(0);
}

float GetCustomControllerPos(uint8_t index)
{
    float sample[CUSTOM_CONTROLLER_ANGLE_COUNT];
    if (index >= CUSTOM_CONTROLLER_ANGLE_COUNT || !GetCustomControllerAngles(sample)) return 0.0f;
    return sample[index];
}
'''


def c_lexical_kinds(text: str) -> str:
    """Classify code, comments and quoted literals without interpreting C.

    Keep an original-offset map across C's backslash/newline splicing so a
    continued // comment or split /* opener cannot hide an owned hook. Quoted
    delimiters and escapes are consumed as literals, never as comment syntax.
    This is only lexical admission for pinned snippets, not a C/preprocessor
    verifier (for example, it does not evaluate conditional compilation).
    """
    chars, offsets = [], []
    index = 0
    while index < len(text):
        splice = re.match(r"\\\r?\n", text[index:index + 3])
        if splice:
            index += len(splice.group())
        else:
            chars.append(text[index])
            offsets.append(index)
            index += 1
    logical = "".join(chars)
    kinds = ["c"] * len(text)
    index = 0
    while index < len(logical):
        start = index
        if logical.startswith("//", index):
            newline = logical.find("\n", index + 2)
            index = len(logical) if newline == -1 else newline
            kind = "m"
        elif logical.startswith("/*", index):
            end = logical.find("*/", index + 2)
            if end == -1:
                raise RuntimeError("controller angle source: unterminated C comment")
            index, kind = end + 2, "m"
        elif logical[index] in ("\"", "'"):
            quote = logical[index]
            index += 1
            while index < len(logical):
                if logical[index] == "\\":
                    index += 2
                elif logical[index] == quote:
                    index += 1
                    break
                elif logical[index] in "\r\n":
                    raise RuntimeError("controller angle source: unterminated C literal")
                else:
                    index += 1
            else:
                raise RuntimeError("controller angle source: unterminated C literal")
            kind = "q"
        else:
            index += 1
            continue
        first, last = offsets[start], offsets[index - 1] + 1
        kinds[first:last] = [kind] * (last - first)
    return "".join(kinds)


def live_code(text: str) -> str:
    """Preserve offsets/lines while hiding comments and quoted literal text."""
    return "".join(char if kind == "c" or char in "\r\n" else " "
                   for char, kind in zip(text, c_lexical_kinds(text)))


def live_fragment(text: str, fragment: str, label: str) -> None:
    start = text.index(fragment)
    actual = c_lexical_kinds(text)[start:start + len(fragment)]
    expected = c_lexical_kinds(fragment)
    if any(real != wanted for char, real, wanted in zip(fragment, actual, expected)
           if not char.isspace()):
        raise RuntimeError(f"{label}: controller angle hook is commented out or quoted")


def once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"{label}: unsupported or ambiguous source anchor")
    live_fragment(text, old, label)
    return text.replace(old, new, 1)


def installed_once(text: str, fragment: str, label: str) -> None:
    """A marker is not evidence that its safety-sensitive integration survived."""
    if text.count(fragment) != 1:
        raise RuntimeError(f"{label}: installed controller angle hook missing, edited or duplicated")
    live_fragment(text, fragment, label)


def owned_change(text: str, old: str, new: str, label: str, installed: bool) -> str:
    if installed:
        installed_once(text, new, label)
        return text
    return once(text, old, new, label)


def patch_referee(text: str) -> str:
    installed = MARK in text
    if installed:
        installed_once(text, IMPLEMENTATION.strip(), "referee implementation")
    else:
        text = once(text, "void init_referee_struct_data(void)", IMPLEMENTATION + "\nvoid init_referee_struct_data(void)", "referee implementation")
    text = owned_change(text, "void init_referee_struct_data(void)\n{", "void init_referee_struct_data(void)\n{\n    CustomControllerAnglesReset();", "referee init", installed)
    text = owned_change(text, "robot_custom_data_t * GetCustomControllerDataPoint(void) { return &robot_custom_data; }",
                "CustomControllerData_t * GetCustomControllerDataPoint(void) { return &custom_controller_data; }",
                "raw angle payload source", installed)
    dispatch = re.search(r"^void referee_data_solve\(uint8_t \*\s*frame\)\s*\{.*?^\}", live_code(text), re.M | re.S)
    if dispatch is None:
        raise RuntimeError("referee dispatch: controller angle hook missing or edited")
    # The KM/typed dispatcher may already provide this guard away from the
    # opening brace, or add a second one. Validate inside this function only.
    if "if (frame == 0) return;" not in dispatch.group():
        if installed:
            raise RuntimeError("referee null frame guard: installed controller angle hook missing or edited")
        text = once(text, "void referee_data_solve(uint8_t * frame)\n{",
                    "void referee_data_solve(uint8_t * frame)\n{\n    if (frame == 0) return;", "null frame guard")
    anchor = "        case CUSTOM_CONTROLLER_CMD_ID: {\n"
    # Header bytes contain payload length even when the optional typed-dispatch
    # patch defers publishing referee_receive_header until after validation.
    text = owned_change(text, anchor, anchor + "            if (!CustomControllerAnglesAccept(frame + index,\n"
                "                (uint16_t)((uint16_t)frame[1] | ((uint16_t)frame[2] << 8)))) return;\n", "0x0302 acceptance", installed)
    legacy = r"inline float GetCustomControllerPos\(uint8_t index\)\s*\{.*?\n\}"
    if installed:
        if re.search(legacy, live_code(text), flags=re.S):
            raise RuntimeError("legacy angle getter remains beside installed controller angle hooks")
        return text
    matches = list(re.finditer(legacy, text, flags=re.S))
    if len(matches) != 1:
        raise RuntimeError("legacy angle getter layout not recognized")
    return once(text, matches[0].group(), "", "legacy angle getter")


def patch_header(text: str) -> str:
    installed = MARK in text
    text = owned_change(text, "extern robot_custom_data_t * GetCustomControllerDataPoint(void);",
                "/* Raw last payload only; control consumers must use the fresh snapshot API. */\n"
                "extern CustomControllerData_t * GetCustomControllerDataPoint(void);", "raw angle pointer declaration", installed)
    return owned_change(text, "extern inline float GetCustomControllerPos(uint8_t index);", DECLARATIONS, "referee header", installed)


def patch_arm(text: str) -> str:
    installed = MARK in text
    text = owned_change(text, "    MA.custom_controller_ready = GetRefereeState();", "    MA.custom_controller_ready = GetCustomControllerOnline();  /* " + MARK + " */", "arm observer", installed)
    old = """            if (MA.custom_controller_ready) {
                float pos[6] = {0};
                pos[J0] = GetCustomControllerPos(J0);
                pos[J1] = GetCustomControllerPos(J1);
                pos[J2] = GetCustomControllerPos(J2);
                pos[J3] = GetCustomControllerPos(J3);
                pos[J4] = GetCustomControllerPos(J4);
                pos[J5] = GetCustomControllerPos(J5);"""
    new = """            float pos[CUSTOM_CONTROLLER_ANGLE_COUNT];
            /* Check again at consumption; observer readiness is only status.
             * Existing SAFE output inhibition is not a gravity-safe hold. */
            MA.custom_controller_ready = GetCustomControllerAngles(pos);
            if (!MA.custom_controller_ready) {
                MA.mode = MECHANICAL_ARM_SAFE;
                break;
            }
            {"""
    text = owned_change(text, old, new, "arm snapshot", installed)
    # Division before addition avoids overflow for finite wire values; actual
    # joint reference limits and the existing J0..J2 jump gate remain unchanged.
    text = owned_change(text, "float vj4_pos = (pos[J4] - pos[J5]) / 2;", "float vj4_pos = pos[J4] / 2.0f - pos[J5] / 2.0f;", "joint differential", installed)
    text = owned_change(text, "float vj5_pos = (pos[J4] + pos[J5]) / 2;", "float vj5_pos = pos[J4] / 2.0f + pos[J5] / 2.0f;", "joint sum", installed)
    text = owned_change(text, "void MechanicalArmConsole(void)\n{", """void MechanicalArmConsole(void)
{
    /* Expiry between Reference and Console must not apply the old target. */
    if (MA.mode == MECHANICAL_ARM_FOLLOW && !GetCustomControllerOnline()) {
        MA.custom_controller_ready = false;
        MA.mode = MECHANICAL_ARM_SAFE;
    }""", "arm output expiry", installed)
    return text


def patch_sender(text: str) -> str:
    installed = MARK in text
    old = """    DataConcatenat(data, DATA_LENGTH);
    HAL_UART_Transmit(&huart1, (uint8_t *)(&TX_DATA), sizeof(TX_DATA), 50);"""
    new = """    /* POLAR-CONTROLLER-ANGLE: cc_control_data is only 28 bytes, and the
     * engineer source defines six joints. Never read 30 bytes from it. */
    uint8_t payload[DATA_LENGTH] = {0};
    if (data == 0) return;
    memcpy(payload, data, CUSTOM_CONTROLLER_ANGLE_COUNT * sizeof(float));
    DataConcatenat(payload, DATA_LENGTH);
    HAL_UART_Transmit(&huart1, (uint8_t *)(&TX_DATA), sizeof(TX_DATA), 50);"""
    return owned_change(text, old, new, "bounded controller sender", installed)


def patch_task(text: str) -> str:
    installed = MARK in text
    return owned_change(text,
        "        if (xTaskGetTickCount() - lastTick > CUSTOM_CONTROLLER_SEND_TIME) {\n            SendDataToPC((uint8_t *)cc_control_data.pos);",
        "        if ((uint32_t)(xTaskGetTickCount() - lastTick) >= CUSTOM_CONTROLLER_SEND_TIME) {\n"
        "            lastTick = xTaskGetTickCount();  /* POLAR-CONTROLLER-ANGLE: bounded 30 Hz */\n"
        "            SendDataToPC((uint8_t *)cc_control_data.pos);", "controller rate limit", installed)


PATCHERS = (patch_referee, patch_header, patch_arm, patch_sender, patch_task)


def render(root: Path) -> dict[str, str]:
    result = {}
    for relative, patcher in zip(OWNED, PATCHERS):
        path = root / relative
        for component in (path, *path.parents):
            if component == root:
                break
            if component.is_symlink():
                raise RuntimeError(f"Symlinked firmware source path: {relative}")
        if not path.is_file():
            raise RuntimeError(f"Missing or symlinked firmware source: {relative}")
        result[relative] = patcher(path.read_text(encoding="utf-8"))
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("firmware_root", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--revert", action="store_true")
    args = parser.parse_args(argv)
    if args.dry_run and args.revert:
        parser.error("--dry-run and --revert are mutually exclusive")
    root = args.firmware_root.resolve()
    try:
        journal = FileJournal(root, OWNED)
        # Do not collide with the broader hero/KM installer snapshot.
        journal.path = journal.path.with_name("polar-controller-angle-snapshot.json")
        journal.lock = journal.lock.with_name("polar-controller-angle-snapshot.lock")
        if args.dry_run:
            changed = render(root)
            print(f"PASS: recognized {len(changed)} source files; no writes")
            return 0
        with journal.locked():
            if args.revert:
                print(f"Restored {journal.revert()} controller-angle source files")
                return 0
            result = render(root)  # Validate every anchor before touching any file.
            journal.begin()
            for relative, content in result.items():
                path = root / relative
                if path.read_text(encoding="utf-8") != content:
                    path.write_text(content, encoding="utf-8")
            journal.finish()
        print("PASS: controller angle source patch installed; no firmware build, flash or hardware operation")
        return 0
    except (OSError, RuntimeError, SnapshotError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
