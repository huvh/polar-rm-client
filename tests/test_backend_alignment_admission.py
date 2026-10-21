"""Offline profile/role/freshness admission; never opens a transport."""
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rm_client.backend.qualification import (CORE_TESTS, OPTIONAL_TESTS, DYNAMIC_TESTS,
    QualificationEvidenceStore, QualificationManager, core_profile_support)
from rm_client.backend.readiness import audit_backend
from rm_client.referee_profiles import DEFAULT_PROFILE, STUDENT_PREVIEW_PROFILE, V2_PROFILE
from rm_client.model import RobotState

class QualificationRoleTests(unittest.TestCase):
    def manager(self, robot='3', hero=False):
        directory=tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        q=QualificationManager(QualificationEvidenceStore(Path(directory.name), build_commit='a'*40))
        q.new_session(robot_id=robot, firmware_hash='b'*64, match_mode='RMUC7v7', video_source='udp', operator='operator')
        for key in CORE_TESTS:
            if key != 'field_signoff': q.record_automatic(key, True)
        if hero: q.record_automatic('hero_deploy_status_test', True)
        q.sign_off('safety-lead')
        return q
    def test_non_hero_core_does_not_require_deploy(self):
        for robot in ('2','3','4','5','6','8','102','103','108'):
            q=self.manager(robot)
            self.assertTrue(q.core_ready()[0]); self.assertIn('core_kmc',q.capabilities())
            self.assertNotIn('hero',q.capabilities())
    def test_hero_is_role_specific_and_still_requires_own_evidence(self):
        for robot in ('1','101'):
            self.assertNotIn('hero',self.manager(robot).capabilities())
            self.assertIn('hero',self.manager(robot,True).capabilities())
        self.assertNotIn('hero',self.manager('3',True).capabilities())
    def test_hero_record_remains_signed_and_dynamic(self):
        self.assertNotIn('hero_deploy_status_test',CORE_TESTS)
        self.assertIn('hero_deploy_status_test',OPTIONAL_TESTS)
        self.assertIn('hero_deploy_status_test',DYNAMIC_TESTS)
        q=self.manager('1',True)
        before=q._technical_digest(); q.session.tests['hero_deploy_status_test'].notes='changed'
        self.assertNotEqual(before,q._technical_digest()); self.assertFalse(q.core_ready()[0])
    def test_role_change_cannot_retain_hero_capability(self):
        q=self.manager('1',True); self.assertIn('hero',q.capabilities())
        q.session.robot_id='3'; self.assertNotIn('hero',q.capabilities())
    def test_profile_support_uses_real_publish_contract(self):
        self.assertTrue(core_profile_support(DEFAULT_PROFILE)[0])
        self.assertFalse(core_profile_support(STUDENT_PREVIEW_PROFILE)[0])
        self.assertFalse(core_profile_support('invalid')[0])
        with patch('rm_client.backend.qualification.get_profile',return_value=SimpleNamespace(profile_id=V2_PROFILE, validate_publish=lambda topic,qos:(False,'partial'))):
            self.assertEqual(core_profile_support(V2_PROFILE),(False,'partial'))

class ReadinessProfileTests(unittest.TestCase):
    def gates(self,state,manager=None):
        with patch('rm_client.backend.readiness.time.perf_counter',return_value=100.), patch('rm_client.backend.readiness._ffmpeg_available',return_value=False):
            return {g.key:g for g in audit_backend(manager,state).gates}
    def test_receipt_clock_rejects_future_nonfinite_and_malformed(self):
        state=RobotState(); state.official_events_online=True
        for receipt in (True,'99',None,float('inf'),float('nan'),-1,0,100.01,10**400):
            state.official_feed_at=receipt
            self.assertFalse(self.gates(state)['fresh_referee_state'].passed)
        for receipt in (98.,100):
            state.official_feed_at=receipt
            self.assertTrue(self.gates(state)['fresh_referee_state'].passed)
    def test_active_profile_not_global_v1_constant(self):
        state=RobotState(referee_profile=STUDENT_PREVIEW_PROFILE)
        gates=self.gates(state)
        self.assertNotIn('protocol_v1_3_1',gates)
        self.assertFalse(gates['referee_protocol'].passed)
        self.assertIn(STUDENT_PREVIEW_PROFILE,gates['referee_protocol'].detail)
    def test_hero_hardware_gate_only_required_for_hero(self):
        state=RobotState()
        for rid in (2,3,6,8):
            state.robot_id=rid
            self.assertFalse(self.gates(state)['hero_deploy_status_test'].required)
        for rid in (1,101):
            state.robot_id=rid
            self.assertTrue(self.gates(state)['hero_deploy_status_test'].required)

class ArmRaceTests(unittest.TestCase):
    def host(self):
        from rm_client.backend.manager import BackendManager
        from rm_client.backend.safety import OfficialSafety
        safety=OfficialSafety(); safety.allow_mqtt_publish=True
        mqtt=SimpleNamespace(mock_output=False,connected=True,subscriptions_ready=True,
            client=object(),client_id='3',receive_generation=1)
        session=SimpleNamespace(robot_id='3',match_mode='RMUC7v7')
        qualification=SimpleNamespace(verified_core_ready=lambda:(True,'ok'),session=session,
            identity_matches=lambda **kw:(True,'ok'),capabilities=lambda:frozenset({'core_kmc'}))
        host=SimpleNamespace(mqtt=mqtt,safety=safety,qualification=qualification,
            state=SimpleNamespace(robot_id=3,match_mode='RMUC7v7'),
            referee=SimpleNamespace(profile_id=DEFAULT_PROFILE),
            _drain_input_clear=lambda:None,_backend_transition_blocks_work=lambda:False,
            _input_clear_incomplete=lambda:False,_canonical_readiness_video_source=lambda:'udp',
            field_log=SimpleNamespace(emit=lambda *a,**kw:None))
        return host, BackendManager.arm_match_control
    def test_current_suback_is_required_before_evidence(self):
        host, arm=self.host(); host.mqtt.subscriptions_ready=False
        host.qualification.verified_core_ready=lambda: self.fail('must not inspect evidence yet')
        self.assertFalse(arm(host,firmware_hash='b'*64)[0])
    def test_reconnect_during_verified_load_does_not_arm(self):
        host,arm=self.host()
        def reload():
            host.mqtt.receive_generation+=1
            return True,'ok'
        host.qualification.verified_core_ready=reload
        self.assertFalse(arm(host,firmware_hash='b'*64)[0])
        self.assertEqual(host.safety.control_state.value,'LOCKED')
    def test_observer_revocation_is_not_success(self):
        host,arm=self.host()
        def hook(reason):
            if 'armed' in reason: host.safety.lock_control('observer revoked',notify=False)
        host.safety.input_clear_hook=hook
        self.assertFalse(arm(host,firmware_hash='b'*64)[0])
    def test_stable_owner_can_arm(self):
        host,arm=self.host()
        self.assertEqual(arm(host,firmware_hash='b'*64),(True,'MATCH_ARMED'))

if __name__=='__main__': unittest.main()
