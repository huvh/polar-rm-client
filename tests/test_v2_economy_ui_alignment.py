"""Inert dialog tests against real V2 quote rules and production payload codecs."""
from dataclasses import replace
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_hud_display_locale import Host
from rm_client.backend.referee.registry import get_profile, V2_PROFILE
from rm_client.backend.referee.rm2026_v2.observations import WireSnapshot, WireObservation
from rm_client.match_modes import MATCH_MODES
from rm_client.ui.polar.renderers import v2_economy_dialog as ed


def host_fixture(robot=3, stage=4):
    h=Host('English');h.match_mode_manager.current=MATCH_MODES['RMUC7v7'];h.state.match_mode='RMUC7v7'
    h.state.robot_id=robot
    h.state.robot_profile='Aerial' if robot in {6,106} else 'Infantry1'
    session=NS(session_id='session',operator='operator',referee_profile=V2_PROFILE,robot_id=str(robot),match_mode='RMUC7v7')
    profile=get_profile(V2_PROFILE)
    data={
        'GameStatus':dict(current_stage=stage,current_round=1,stage_countdown_sec=400),
        'RobotStaticStatus':dict(robot_id=robot,robot_type=3,connection_state=1,field_state=0,alive_state=1,max_health=500,level=1),
        'GlobalLogisticsStatus':dict(remaining_economy=1000),
        'RobotDynamicStatus':dict(current_health=300,is_out_of_combat=True,can_remote_ammo=True,can_remote_heal=True),
        'RobotRespawnStatus':dict(is_pending_respawn=True,can_free_respawn=True,can_pay_for_respawn=True,gold_cost_for_respawn=31),
        'RobotPerformanceSelectionSync':dict(sentry_control=0),
        'SentryStatusSync':dict(posture_id=1,is_weakened=False,is_powered=False),
    }
    snapshot=WireSnapshot(V2_PROFILE,4,str(robot),100.,tuple(WireObservation(m,f,v,100.) for m,values in data.items() for f,v in values.items()))
    mqtt=NS(referee=profile,client=object(),receive_generation=4,client_id=str(robot),mock_output=False,connected=True,snapshot=snapshot)
    mqtt.v2_wire_snapshot=lambda:mqtt.snapshot
    h.calls=[];h.locks=[];h.prompts=[]
    mqtt.publish_topic=lambda topic,payload,**kwargs:h.calls.append((topic,payload,kwargs)) or (True,'ok')
    h.backend=NS(referee=profile,mqtt=mqtt,qualification=NS(session=session),lock_control=lambda:h.locks.append(True))
    h.scenario_manager=NS(current=NS(key='OfficialEvent'))
    h._economy_qualification_token='one-token'
    h._v2_air_qualification_attempt=None
    return h


def update(h,message,field,value,received_at=100.):
    old=h.backend.mqtt.snapshot
    obs=tuple(WireObservation(m.message,m.field,value if (m.message,m.field)==(message,field) else m.value,
          received_at if (m.message,m.field)==(message,field) else m.received_at) for m in old.observations)
    h.backend.mqtt.snapshot=replace(old,observations=obs,received_at=received_at)


class EconomyDialogTests(unittest.TestCase):
    def drive(self,h,index,topic='CommonCommand',param=10,question=None):
        def ask(owner,title,text,*args):
            h.prompts.append(text)
            return question(len(h.prompts)) if question else ed.QMessageBox.StandardButton.Yes
        with patch.object(ed.time,'perf_counter',return_value=100.), \
             patch.object(ed.QInputDialog,'getItem',side_effect=lambda o,t,p,choices,*args:(choices[index],True)), \
             patch.object(ed.QInputDialog,'getInt',return_value=(param,True)), \
             patch.object(ed.QInputDialog,'getDouble',side_effect=[(1.25,True),(2.5,True)]), \
             patch.object(ed.QMessageBox,'question',side_effect=ask):
            ed._open_v2_economy_dialog(h,topic)

    def test_common_local_quantity_and_remote_fixed_pack(self):
        for index,param,command in ((0,20,1),(4,999,5),(5,999,6)):
            h=host_fixture();self.drive(h,index,param=param)
            self.assertEqual(len(h.calls),1,h.toasts)
            self.assertEqual(h.calls[0][1],get_profile(V2_PROFILE).codec.encode_common_command(command,param if command==1 else 0))
            self.assertEqual(h.calls[0][2]['intent'],'economy')
            self.assertEqual(h.calls[0][2]['qualification_token'],'one-token')
            self.assertIs(h.calls[0][2]['expected_economy_snapshot'],h.backend.mqtt.snapshot)
            self.assertIsNone(h._economy_qualification_token)
            self.assertEqual(len(h.locks),1)
            if command==5:self.assertIn('150 coins',h.prompts[0])

    def test_paid_respawn_uses_current_wire_quote(self):
        h=host_fixture();update(h,'RobotStaticStatus','alive_state',2)
        self.drive(h,3)
        self.assertEqual(len(h.calls),1,h.toasts)
        self.assertIn('31 coins',h.prompts[0])
        self.assertEqual(h.calls[0][1],get_profile(V2_PROFILE).codec.encode_common_command(4,0))

    def test_sentry_intervention_fee_and_missing_target_quote(self):
        for index,command,cost in ((0,1,100),(1,3,200),(5,7,50)):
            h=host_fixture(6);self.drive(h,index,'SentryCtrlCommand')
            self.assertEqual(len(h.calls),1,h.toasts)
            self.assertEqual(h.calls[0][1],get_profile(V2_PROFILE).codec.encode_sentry_ctrl_command(command))
            self.assertIn(f'{cost} coins',h.prompts[0])
        h=host_fixture(6);self.drive(h,4,'SentryCtrlCommand')
        self.assertEqual(h.calls,[])
        self.assertTrue(any('quote' in t for t in h.toasts))

    def test_paid_map_payload_has_same_team_target_and_correct_field_semantics(self):
        for robot,target in ((3,7),(103,107)):
            h=host_fixture(robot);self.drive(h,1,'MapClickCmd')
            self.assertEqual(len(h.calls),1,h.toasts)
            expected=get_profile(V2_PROFILE).codec.encode_map_click_cmd(is_send_all=0,robot_id=bytes([target])+bytes(6),mode=1,mark_type=2,map_x=1.25,map_y=2.5)
            self.assertEqual(h.calls[0][1],expected)
            self.assertIn(f'Sentry#{target}',h.prompts[0])
            self.assertIn('(1.25, 2.5)m',h.prompts[0])

    def test_cancel_never_sends_or_consumes_token(self):
        h=host_fixture();self.drive(h,4,question=lambda n:ed.QMessageBox.StandardButton.No)
        self.assertEqual(h.calls,[]);self.assertEqual(h.locks,[])
        self.assertEqual(h._economy_qualification_token,'one-token')

    def test_each_actual_match_mode_source_is_required(self):
        for owner in ('ui','state','session'):
            h=host_fixture()
            if owner=='ui':h.match_mode_manager.current=MATCH_MODES['RMUL3v3']
            elif owner=='state':h.state.match_mode='RMUL3v3'
            else:h.backend.qualification.session.match_mode='RMUL3v3'
            self.drive(h,4)
            self.assertEqual(h.calls,[])
            self.assertTrue(any('RMUC7v7' in t for t in h.toasts))

    def test_context_changes_during_confirmation_cancel_without_retry(self):
        for change in ('client','mode','session','round'):
            h=host_fixture()
            def question(n):
                if change=='client':h.backend.mqtt.client=object()
                elif change=='mode':h.state.match_mode='RMUL3v3'
                elif change=='session':h.backend.qualification.session=NS(**vars(h.backend.qualification.session))
                else:update(h,'GameStatus','current_round',2)
                return ed.QMessageBox.StandardButton.Yes
            self.drive(h,4,question=question)
            self.assertEqual(h.calls,[])
            self.assertEqual(len(h.prompts),1)

    def test_unrelated_refresh_can_send_latest_exact_snapshot(self):
        h=host_fixture()
        def question(n):
            update(h,'RobotStaticStatus','level',2)
            return ed.QMessageBox.StandardButton.Yes
        self.drive(h,4,question=question)
        self.assertEqual(len(h.calls),1,h.toasts)
        self.assertEqual(len(h.prompts),1)
        self.assertIs(h.calls[0][2]['expected_economy_snapshot'],h.backend.mqtt.snapshot)

    def test_price_change_reconfirms_at_most_once(self):
        for continual in (False,True):
            h=host_fixture();update(h,'RobotStaticStatus','alive_state',2)
            def question(n):
                if n==1 or continual:update(h,'RobotRespawnStatus','gold_cost_for_respawn',31+n)
                return ed.QMessageBox.StandardButton.Yes
            self.drive(h,3,question=question)
            self.assertEqual(len(h.prompts),2)
            self.assertEqual(len(h.calls),0 if continual else 1)
            self.assertIn('32 coins',h.prompts[1])

    def test_final_rejection_consumes_token_locks_once_without_retry(self):
        h=host_fixture()
        def reject(topic,payload,**kwargs):h.calls.append((topic,payload,kwargs));return False,'state updated; please reconfirm'
        h.backend.mqtt.publish_topic=reject
        self.drive(h,4)
        self.assertEqual(len(h.calls),1);self.assertEqual(len(h.locks),1)
        self.assertEqual(h.toasts[-1],'state updated; please reconfirm')

    def test_invalid_quantity_does_not_publish(self):
        for quantity in (0,11,1001,True,float('inf')):
            h=host_fixture();self.drive(h,0,param=quantity)
            self.assertEqual(h.calls,[]);self.assertEqual(h.prompts,[])


if __name__=='__main__':unittest.main()
