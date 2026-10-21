"""Final transport-bound policy is read-only, including expired authority."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rm_client.backend.safety import OfficialSafety
class FinalPolicyTests(unittest.TestCase):
    def policy(self):
        p=OfficialSafety();p.allow_mqtt_publish=True;p.enforce_official_limits=True
        p.update_stage(4,now=100);p.arm_match({'core_kmc'})
        return p
    def test_fresh_match_and_expiration_are_readonly(self):
        p=self.policy();called=[];p.input_clear_hook=called.append
        before=(p.control_generation,p.last_reason,p.control_state)
        self.assertTrue(p.can_publish_current('KeyboardMouseControl',now=100.5)[0])
        self.assertFalse(p.can_publish_current('KeyboardMouseControl',now=101)[0])
        self.assertEqual(before,(p.control_generation,p.last_reason,p.control_state));self.assertEqual(called,[])
    def test_final_capability_and_rate_match_initial_gate(self):
        p=self.policy()
        self.assertFalse(p.can_publish_current('CommonCommand',now=100.1,intent='economy')[0])
        p._publish_at['KeyboardMouseControl']=100.1
        self.assertFalse(p.can_publish_current('KeyboardMouseControl',now=100.1001)[0])
    def test_invalid_clock_is_readonly_denial(self):
        p=self.policy()
        for now in (True,None,'100',float('inf'),float('nan'),10**400):
            self.assertFalse(p.can_publish_current('KeyboardMouseControl',now=now)[0])
    def test_token_does_not_grant_economy_match_exception(self):
        from unittest.mock import patch
        p=self.policy()
        with patch('rm_client.backend.safety.time.perf_counter',return_value=100.):
            token=p.begin_qualification({'core_kmc'},ttl_s=15.)
        p.update_stage(1,now=100)
        self.assertTrue(p.can_publish_current('RobotPerformanceSelectionCommand',now=100.1,intent='core_kmc',qualification_token=token.value)[0])
        self.assertFalse(p.can_publish_current('RobotPerformanceSelectionCommand',now=116,intent='core_kmc',qualification_token=token.value)[0])
        self.assertFalse(p.can_publish_v2_economy_current('CommonCommand',now=100.1,qualification_token=token.value)[0])
if __name__=='__main__':unittest.main()
