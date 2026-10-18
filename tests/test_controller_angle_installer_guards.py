"""Installer admission on synthetic source fixtures, never a real firmware tree.

These snippets exercise the pinned source transformations and CLI refusal. They
do not compile firmware or qualify board behavior. All writes stay in temp dirs.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/firmware/controller_angle/apply_controller_angle.py"
spec = importlib.util.spec_from_file_location("angle_installer_guards", SCRIPT)
angle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(angle)

# Minimal textual fixtures for the existing, pinned installer anchors. These
# intentionally have no board definitions, serial ports, or executable main.
ORIGINALS = (
    """#include "protocol.h"
robot_custom_data_3_t robot_custom_data_3;
void init_referee_struct_data(void)
{
}
robot_custom_data_t * GetCustomControllerDataPoint(void) { return &robot_custom_data; }
void referee_data_solve(uint8_t * frame)
{
    if (HAL_GetTick() - referee_online_time > REFEREE_TIMEOUT) {
        referee_receive_count = 0;
    }
    referee_receive_count++;
    memcpy(&referee_receive_header, frame, sizeof(frame_header_struct_t));
    switch (cmd_id) {
        case CUSTOM_CONTROLLER_CMD_ID: {
            memcpy(&custom_controller_data, frame + index, sizeof(CustomControllerData_t));
        } break;
        case STUDENT_INTERACTIVE_DATA_CMD_ID: {
            memcpy(&student_interactive_data, frame + index, sizeof(student_interactive_data_t));
        } break;
        case ROBOT_CUSTOM_DATA_3_CMD_ID: {
            memcpy(&robot_custom_data_3, frame + index, sizeof(robot_custom_data_3_t));
        } break;
        default: {
            referee_receive_count--;
            break;
        }
    }
}
inline float GetCustomControllerPos(uint8_t index)
{
    return 0.0f;
}
""",
    """extern robot_custom_data_t * GetCustomControllerDataPoint(void);
extern inline float GetCustomControllerPos(uint8_t index);
""",
    """void MechanicalArmObserve(void)
{
    MA.custom_controller_ready = GetRefereeState();
}
void MechanicalArmReference(void)
{
            if (MA.custom_controller_ready) {
                float pos[6] = {0};
                pos[J0] = GetCustomControllerPos(J0);
                pos[J1] = GetCustomControllerPos(J1);
                pos[J2] = GetCustomControllerPos(J2);
                pos[J3] = GetCustomControllerPos(J3);
                pos[J4] = GetCustomControllerPos(J4);
                pos[J5] = GetCustomControllerPos(J5);
                float vj4_pos = (pos[J4] - pos[J5]) / 2;
                float vj5_pos = (pos[J4] + pos[J5]) / 2;
            }
}
void MechanicalArmConsole(void)
{
}
""",
    """void SendDataToPC(uint8_t *data)
{
    DataConcatenat(data, DATA_LENGTH);
    HAL_UART_Transmit(&huart1, (uint8_t *)(&TX_DATA), sizeof(TX_DATA), 50);
}
""",
    """void custom_controller_task(void)
{
        if (xTaskGetTickCount() - lastTick > CUSTOM_CONTROLLER_SEND_TIME) {
            SendDataToPC((uint8_t *)cc_control_data.pos);
        }
}
""",
)


class ControllerAngleInstallerGuards(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="angle-installer-guards-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        # The journal only requires a local metadata directory. No git command
        # or user repository is needed for these disposable source snippets.
        (self.root / ".git").mkdir()
        self.write_sources(ORIGINALS)

    def write_sources(self, sources):
        for relative, source in zip(angle.OWNED, sources):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)

    def installed_sources(self):
        return tuple(patcher(source) for patcher, source in zip(angle.PATCHERS, ORIGINALS))

    def snapshot(self):
        return {path.relative_to(self.root).as_posix(): path.read_bytes()
                for path in self.root.rglob("*") if path.is_file()}

    def cli(self, *options):
        return subprocess.run([sys.executable, str(SCRIPT), str(self.root), *options],
                              capture_output=True, text=True, timeout=10)

    def assert_refused_without_mutation(self):
        before = self.snapshot()
        for options in (("--dry-run",), ()):
            with self.subTest(options=options):
                result = self.cli(*options)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("FAIL:", result.stderr)
                self.assertNotIn("PASS:", result.stdout)
                self.assertEqual(self.snapshot(), before)

    def test_marker_only_files_cannot_claim_success(self):
        sources = list(self.installed_sources())
        for index in (2, 3, 4):
            with self.subTest(file=angle.OWNED[index]):
                changed = sources.copy()
                changed[index] = "/* POLAR-CONTROLLER-ANGLE */\n"
                self.write_sources(changed)
                self.assert_refused_without_mutation()

    def test_implementation_and_declarations_without_hooks_are_rejected(self):
        sources = list(self.installed_sources())
        for index, replacement in ((0, angle.IMPLEMENTATION), (1, angle.DECLARATIONS)):
            with self.subTest(file=angle.OWNED[index]):
                changed = sources.copy()
                changed[index] = replacement
                self.write_sources(changed)
                self.assert_refused_without_mutation()

    def test_each_removed_or_changed_installed_hook_is_rejected(self):
        mutations = (
            (0, "    CustomControllerAnglesReset();", ""),
            (0, "return &custom_controller_data;", "return &robot_custom_data;"),
            (0, "if (!CustomControllerAnglesAccept(frame + index,", "if (CustomControllerAnglesAccept(frame + index,"),
            (0, "    if (frame == 0) return;", ""),
            (1, "extern CustomControllerData_t * GetCustomControllerDataPoint(void);", ""),
            (2, "MA.custom_controller_ready = GetCustomControllerOnline();", "MA.custom_controller_ready = GetRefereeState();"),
            (2, "MA.custom_controller_ready = GetCustomControllerAngles(pos);", "MA.custom_controller_ready = true;"),
            (2, "if (!MA.custom_controller_ready)", "if (false)"),
            (2, "if (MA.mode == MECHANICAL_ARM_FOLLOW && !GetCustomControllerOnline())", "if (false)"),
            (2, "float vj4_pos = pos[J4] / 2.0f - pos[J5] / 2.0f;", "float vj4_pos = (pos[J4] - pos[J5]) / 2;"),
            (2, "float vj5_pos = pos[J4] / 2.0f + pos[J5] / 2.0f;", "float vj5_pos = (pos[J4] + pos[J5]) / 2;"),
            (3, "memcpy(payload, data, CUSTOM_CONTROLLER_ANGLE_COUNT * sizeof(float));", "memcpy(payload, data, DATA_LENGTH);"),
            (3, "uint8_t payload[DATA_LENGTH] = {0};", "uint8_t payload[DATA_LENGTH];"),
            (3, "if (data == 0) return;", ""),
            (3, "DataConcatenat(payload, DATA_LENGTH);", "DataConcatenat(data, DATA_LENGTH);"),
            (4, "lastTick = xTaskGetTickCount();", "lastTick = 0;"),
            (4, ">= CUSTOM_CONTROLLER_SEND_TIME", ">= 0"),
        )
        sources = list(self.installed_sources())
        for index, old, new in mutations:
            with self.subTest(file=angle.OWNED[index], hook=old):
                self.assertEqual(sources[index].count(old), 1)
                changed = sources.copy()
                changed[index] = changed[index].replace(old, new, 1)
                self.write_sources(changed)
                self.assert_refused_without_mutation()

    def test_commented_installed_hooks_cannot_stand_in_for_live_code(self):
        sources = list(self.installed_sources())
        init = "void init_referee_struct_data(void)\n{\n    CustomControllerAnglesReset();\n}"
        joint = "float vj5_pos = pos[J4] / 2.0f + pos[J5] / 2.0f;"
        mutations = (
            (0, init, "/*" + init + "*/\nvoid init_referee_struct_data(void)\n{\n}"),
            (0, "if (frame == 0) return;", "/*if (frame == 0) return;*/"),
            (2, joint, "/*" + joint + "*/"),
            (2, joint, "// " + joint),
            (2, joint, "// continued comment\\\n" + joint),
            (2, joint, '/\\\n*' + joint + '*/'),
            (2, joint, 'const char *removed = "' + joint + '";'),
        )
        for index, old, new in mutations:
            with self.subTest(file=angle.OWNED[index], replacement=new[:70]):
                changed = sources.copy()
                self.assertEqual(changed[index].count(old), 1)
                changed[index] = changed[index].replace(old, new, 1)
                self.write_sources(changed)
                self.assert_refused_without_mutation()

    def test_comments_and_escaped_quoted_delimiters_do_not_change_valid_sources(self):
        decoration = r'''
/* A harmless comment with "quotes", 'apostrophes', and // text. */
const char *literal = "https://example.invalid/a/*b*/c \\\" // still quoted";
const char *literal2 = "escaped backslash \\\\";
const char slash = '/';
const char quote = '\'';
// A harmless trailing line comment
'''
        for sources in (ORIGINALS, self.installed_sources()):
            decorated = tuple(decoration + source + "\n/* ordinary trailing comment */\n"
                              for source in sources)
            self.write_sources(decorated)
            before = self.snapshot()
            result = self.cli("--dry-run")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.snapshot(), before)

    def test_unterminated_comment_and_literal_are_rejected_without_writes(self):
        sources = list(self.installed_sources())
        for suffix in ("\n/* unclosed", '\nconst char *broken = "unclosed'):
            with self.subTest(suffix=suffix):
                changed = sources.copy()
                changed[2] += suffix
                self.write_sources(changed)
                self.assert_refused_without_mutation()

    def test_clean_dry_run_install_idempotence_and_revert(self):
        before = self.snapshot()
        result = self.cli("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.snapshot(), before)
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        installed = self.snapshot()
        for options in (("--dry-run",), ()):
            result = self.cli(*options)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.snapshot(), installed)
        result = self.cli("--revert")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_duplicated_hooks_and_retained_legacy_getter_are_rejected(self):
        sources = list(self.installed_sources())
        duplicates = (
            (0, angle.IMPLEMENTATION),
            (1, angle.DECLARATIONS),
            (2, "float vj5_pos = pos[J4] / 2.0f + pos[J5] / 2.0f;"),
            (0, "inline float GetCustomControllerPos(uint8_t index)\n{\n    return 0.0f;\n}"),
        )
        for index, duplicate in duplicates:
            with self.subTest(file=angle.OWNED[index], duplicate=duplicate[:60]):
                changed = sources.copy()
                changed[index] += "\n" + duplicate + "\n"
                self.write_sources(changed)
                self.assert_refused_without_mutation()

    def test_each_missing_source_marker_cannot_hide_a_partial_install(self):
        sources = list(self.installed_sources())
        for index in range(len(sources)):
            with self.subTest(file=angle.OWNED[index]):
                changed = sources.copy()
                changed[index] = changed[index].replace(angle.MARK, "removed marker")
                self.write_sources(changed)
                self.assert_refused_without_mutation()

    def test_journal_still_protects_later_non_owned_edits(self):
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        path = self.root / angle.OWNED[2]
        path.write_text(path.read_text() + "\n/* later user edit */\n")
        before = self.snapshot()
        for options in ((), ("--revert",)):
            with self.subTest(options=options):
                result = self.cli(*options)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(self.snapshot(), before)

    def test_km_typed_dispatch_composes_in_both_install_orders(self):
        km_path = ROOT / "tools/firmware/km_link/apply_km_link.py"
        km_spec = importlib.util.spec_from_file_location("angle_installer_guards_km", km_path)
        km = importlib.util.module_from_spec(km_spec)
        km_spec.loader.exec_module(km)
        path = self.root / angle.OWNED[0]
        for angle_first in (False, True):
            with self.subTest(angle_first=angle_first):
                source = angle.patch_referee(ORIGINALS[0]) if angle_first else ORIGINALS[0]
                path.write_text(source)
                source = km.apply_referee(path, [])
                source = angle.patch_referee(source)
                path.write_text(source)
                source = km.apply_referee(path, [])
                self.assertEqual(angle.patch_referee(source), source)
                self.assertIn("if (!HostKmFeed(frame + index, payload_length)) return;", source)
                self.assertIn("if (!CustomControllerAnglesAccept(frame + index,", source)

    def test_prepatched_tree_without_journal_is_recognized_and_preserved(self):
        self.write_sources(self.installed_sources())
        before = self.snapshot()
        self.assertEqual(self.cli("--dry-run").returncode, 0)
        self.assertEqual(self.snapshot(), before)
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.cli("--revert").returncode, 0)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
