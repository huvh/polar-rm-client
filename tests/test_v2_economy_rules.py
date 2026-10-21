"""Freshly reconstructed RMUC V2 request estimates, no transport or devices."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rm_client.backend.referee.rm2026_v2.economy_rules import request_decision
from rm_client.backend.referee.rm2026_v2.observations import WireSnapshot,WireObservation
G='GameStatus'; R='RobotStaticStatus'; D='RobotDynamicStatus'; E='GlobalLogisticsStatus'; P='RobotRespawnStatus'; S='SentryStatusSync'; M='RobotPerformanceSelectionSync'
BASE={(G,'current_round'):1,(G,'current_stage'):4,(G,'stage_countdown_sec'):419,
 (R,'robot_id'):3,(R,'robot_type'):1,(R,'connection_state'):1,(R,'field_state'):0,(R,'alive_state'):1,(R,'max_health'):500,
 (D,'is_out_of_combat'):True,(D,'can_remote_ammo'):True,(D,'can_remote_heal'):True,(D,'current_health'):100,
 (E,'remaining_economy'):2000,(P,'is_pending_respawn'):True,(P,'can_free_respawn'):True,(P,'can_pay_for_respawn'):True,(P,'gold_cost_for_respawn'):321,
 (M,'sentry_control'):0,(S,'posture_id'):1,(S,'is_weakened'):False,(S,'is_powered'):False}
def snapshot(robot=3,changes=None,omit=(),receipt=100):
    data=BASE|{(R,'robot_id'):robot}|(changes or {})
    return WireSnapshot('rm2026-v2.0.0',1,str(robot),100,tuple(WireObservation(m,f,v,receipt) for (m,f),v in data.items() if (m,f) not in omit))
def decide(topic,cmd,robot=3,**kw):
    param=kw.pop('param',0); return request_decision(topic,cmd,snapshot(robot,**kw),now=100,param=param)
class EconomyRulesTests(unittest.TestCase):
    def test_common_six_commands_both_alliances(self):
        for blue in (0,100):
            for cmd,robot,param,changes,cost in ((1,3,10,{},10),(2,1,2,{},20),(3,2,0,{(R,'alive_state'):2},0),(4,2,0,{(R,'alive_state'):2},321),(5,1,0,{},150),(6,3,0,{},51)):
                result=decide('CommonCommand',cmd,robot+blue,param=param,changes=changes)
                self.assertTrue(result[0],result);self.assertEqual(result[2],cost)
    def test_common_calibre_quantities_and_no_multipliers(self):
        for cmd,rid,param in ((1,1,10),(1,3,0),(1,3,11),(1,3,1010),(2,3,1),(2,1,101),(5,3,100),(6,1,1)):
            self.assertFalse(decide('CommonCommand',cmd,rid,param=param)[0])
        for param in (True,1.0,'1'):
            self.assertFalse(decide('CommonCommand',1,param=param)[0])
    def test_engineer_only_revives_not_supply_heal(self):
        for cmd in (1,2,5,6):self.assertFalse(decide('CommonCommand',cmd,2,param=10 if cmd==1 else 0)[0])
    def test_respawn_uses_explicit_quote_not_computed_level(self):
        result=decide('CommonCommand',4,2,changes={(R,'alive_state'):2,(P,'gold_cost_for_respawn'):43},omit=((R,'level'),))
        self.assertEqual(result[2],43)
        for field in ('is_pending_respawn','can_pay_for_respawn','gold_cost_for_respawn'):
            self.assertFalse(decide('CommonCommand',4,2,changes={(R,'alive_state'):2},omit=((P,field),))[0])
    def test_remote_explicit_bool_and_health(self):
        for val in (0,1,'true',False):
            self.assertFalse(decide('CommonCommand',5,changes={(D,'can_remote_ammo'):val})[0])
        for hp in (0,500,501):self.assertFalse(decide('CommonCommand',6,changes={(D,'current_health'):hp})[0])
    def test_sentry_fixed_quantities_mode_fee_and_target_boundary(self):
        for rid in (6,106):
            for mode,fee in ((0,50),(1,0)):
                for cmd,base in ((1,50),(3,150),(4,51),(5,0),*( (cmd,0) for cmd in range(7,13))):
                    result=decide('SentryCtrlCommand',cmd,rid,changes={(M,'sentry_control'):mode})
                    self.assertTrue(result[0],result);self.assertEqual(result[2],base+fee)
    def test_sentry6_is_not_given_aerial_quote(self):
        result=decide('SentryCtrlCommand',6,6)
        self.assertFalse(result[0]);self.assertIn('target',result[1]);self.assertIn('quote',result[1])
    def test_sentry_actor_is_aerial_not_target(self):
        for rid in (1,3,7,107):self.assertFalse(decide('SentryCtrlCommand',1,rid)[0])
    def test_sentry_uses_target_fields_not_aerial_dynamic(self):
        omitted=tuple(key for key in BASE if key[0] in {D,P})+((R,'alive_state'),)
        self.assertTrue(decide('SentryCtrlCommand',3,6,omit=omitted)[0])
        self.assertFalse(decide('SentryCtrlCommand',7,6,omit=((S,'posture_id'),))[0])
    def test_map_fee_not_inferred_from_operator_role(self):
        for rid in (1,3,6,103):
            self.assertEqual(decide('MapClickCmd',0,rid)[2],50)
            self.assertEqual(decide('MapClickCmd',0,rid,changes={(M,'sentry_control'):1})[2],0)
    def test_shared_freshness_stage_identity_and_budget(self):
        for changes in ({(G,'current_stage'):1},{(R,'connection_state'):0},{(R,'field_state'):1},{(E,'remaining_economy'):9}):
            self.assertFalse(decide('CommonCommand',1,param=10,changes=changes)[0])
        self.assertFalse(decide('CommonCommand',1,param=10,receipt=97)[0])
        self.assertFalse(decide('CommonCommand',1,param=10,receipt=101)[0])
    def test_unknown_stance_mode_or_missing_target_mode_is_not_default(self):
        for mode in (2,True,'0'):
            self.assertFalse(decide('SentryCtrlCommand',1,6,changes={(M,'sentry_control'):mode})[0])
        self.assertFalse(decide('MapClickCmd',0,omit=((M,'sentry_control'),))[0])
    def test_redcard_is_not_cleared_by_receipt_age(self):
        self.assertFalse(decide('CommonCommand',1,param=10,changes={('PenaltyInfo','penalty_type'):3})[0])
if __name__=='__main__':unittest.main()
