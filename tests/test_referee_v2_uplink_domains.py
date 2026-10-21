"""Pure official213 actor/target and value-domain boundaries; no transport."""
import unittest
from rm_client.backend.referee.rm2026_v2 import codec
from rm_client.backend.referee.rm2026_v2.observations import WireSnapshot, WireObservation
from rm_client.backend.referee.rm2026_v2.uplink_validation import validate_uplink, is_sentry_map
from rm_client.backend.referee.validation import InvalidRefereePayload, MAX_PAYLOAD_BYTES
from rm_client.backend.referee.wire import encode_uint


def witness(robot=3, stage=4, receipt=100.):
    return WireSnapshot('rm2026-v2.0.0', 1, str(robot), receipt, (
        WireObservation('RobotStaticStatus', 'robot_id', robot, receipt),
        WireObservation('GameStatus', 'current_stage', stage, receipt)))


class UplinkDomainTests(unittest.TestCase):
    def check(self, topic, payload, robot=3, stage=4, snapshot=None):
        return validate_uplink(topic, payload, snapshot=snapshot or witness(robot, stage),
                               client_id=str(robot), now=100., require_identity=True)

    def test_role_matrix_is_requester_not_target(self):
        cases = [('AssemblyCommand', codec.encode_assembly_command(0, 4), {2, 102}),
                 ('HeroDeployModeEventCommand', codec.encode_hero_deploy_mode_event_command(1), {1, 101}),
                 ('RuneActivateCommand', codec.encode_rune_activate_command(1), {3, 4, 5, 103, 104, 105}),
                 ('DartCommand', codec.encode_dart_command(1, False, False), {6, 106})]
        for topic, payload, roles in cases:
            for robot in [*range(1, 10), *range(101, 110)]:
                with self.subTest(topic=topic, robot=robot):
                    if robot in roles: self.check(topic, payload, robot)
                    else:
                        with self.assertRaises(InvalidRefereePayload): self.check(topic, payload, robot)

    def test_all_assembly_operations_and_four_difficulties(self):
        for op in range(3):
            for difficulty in range(1, 5):
                self.check('AssemblyCommand', codec.encode_assembly_command(op, difficulty), 2)
        for op, diff in [(3, 1), (0, 0), (0, 5), (1, 5)]:
            with self.assertRaises(InvalidRefereePayload):
                self.check('AssemblyCommand', codec.encode_assembly_command(op, diff), 2)
        self.check('AssemblyCommand', encode_uint(1, 2), 2)

    def test_dart_target_and_booleans_rune_single_intent(self):
        for target in range(1, 6):
            self.check('DartCommand', codec.encode_dart_command(target, True, False), 6)
        for raw in [encode_uint(1, 0), encode_uint(1, 6), encode_uint(1, 1)+encode_uint(2, 2)]:
            with self.assertRaises(InvalidRefereePayload): self.check('DartCommand', raw, 6)
        with self.assertRaises(InvalidRefereePayload): self.check('RuneActivateCommand', b'\x08\x00')

    def test_performance_own_calibre_and_aerial_prepare_scope(self):
        for robot, allowed in [(1, {0, 3, 4}), (3, {0, 1, 2})]:
            for value in range(5):
                raw = codec.encode_robot_performance_selection_command(value, value, 0)
                if value in allowed: self.check('RobotPerformanceSelectionCommand', raw, robot)
                else:
                    with self.assertRaises(InvalidRefereePayload):
                        self.check('RobotPerformanceSelectionCommand', raw, robot)
        for mode in (0, 1):
            raw = codec.encode_robot_performance_selection_command(0, 0, mode)
            self.check('RobotPerformanceSelectionCommand', raw, 6, 1)
            with self.assertRaises(InvalidRefereePayload):
                self.check('RobotPerformanceSelectionCommand', raw, 6, 4)
        with self.assertRaises(InvalidRefereePayload):
            self.check('RobotPerformanceSelectionCommand', codec.encode_robot_performance_selection_command(1, 1, 1), 3)

    def test_identity_is_fresh_and_exact_not_ui_defaults(self):
        raw = codec.encode_dart_command(1, False, False)
        for snapshot in (witness(6, receipt=97.), witness(106), witness(6, receipt=101.)):
            with self.assertRaises(InvalidRefereePayload): self.check('DartCommand', raw, 6, snapshot=snapshot)
        validate_uplink('DartCommand', raw)  # independent mock shape, not authority

    def test_map_ordinary_paid_destination_and_disputed_custom(self):
        for category in (1, 2, 3):
            raw = codec.encode_map_click_cmd(mark_type=category)
            self.assertFalse(is_sentry_map(raw)); self.check('MapClickCmd', raw)
        for category in (4, 5):
            with self.assertRaises(InvalidRefereePayload):
                self.check('MapClickCmd', codec.encode_map_click_cmd(mark_type=category))
        paid = codec.encode_map_click_cmd(is_send_all=2)
        self.assertTrue(is_sentry_map(paid)); self.check('MapClickCmd', paid)
        bad = codec.encode_map_click_cmd(robot_id=bytes([107]))
        self.assertTrue(is_sentry_map(bad))
        with self.assertRaises(InvalidRefereePayload): self.check('MapClickCmd', bad)
        self.check('MapClickCmd', bad, 103)

    def test_route_classifier_is_bounded_before_decode(self):
        with self.assertRaises(InvalidRefereePayload): is_sentry_map(b'\x08\x00' * (MAX_PAYLOAD_BYTES // 2 + 1))
        with self.assertRaises(InvalidRefereePayload): is_sentry_map(b'\x12\xff')

    def test_common_server_fixed_package_and_kmc_strict_bool(self):
        for command in range(3, 7):
            validate_uplink('CommonCommand', codec.encode_common_command(command, 0))
            with self.assertRaises(InvalidRefereePayload):
                validate_uplink('CommonCommand', codec.encode_common_command(command, 100))
        with self.assertRaises(InvalidRefereePayload):
            validate_uplink('CommonCommand', codec.encode_common_command(1, 11))
        with self.assertRaises(InvalidRefereePayload):
            validate_uplink('KeyboardMouseControl', encode_uint(4, 2))
        with self.assertRaises(ValueError):
            validate_uplink('KeyboardMouseControl', encode_uint(6, 65536))

if __name__ == '__main__': unittest.main()
