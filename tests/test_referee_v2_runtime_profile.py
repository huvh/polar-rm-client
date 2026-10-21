"""Opt-in partial V2 profile through actual inert callback/adapter owners."""
from __future__ import annotations
import ast
from copy import deepcopy
import logging
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
import rm_client
from rm_client.backend.mqtt_backend import RmMqttBackend
from rm_client.backend.referee.registry import get_profile
from rm_client.backend.referee.rm2026_v2 import codec
from rm_client.backend.referee.wire import encode_uint, encode_bytes
from rm_client.backend.safety import OfficialSafety, ControlState
from rm_client.combat_events import OfficialMatchFeed
from rm_client.economy import EconomyCommandBridge, EconomyOffer
from rm_client.model import RobotState
from rm_client.referee_profiles import DEFAULT_PROFILE, STUDENT_PREVIEW_PROFILE, V2_PROFILE, supported_profiles, UnsupportedRefereeProfile
from rm_client.top_match_bar import TopMatchBarFeed
from rm_client.robot_profiles import profiles_for_match
from rm_client.ui.jello_locale import option_label
from rm_client import student_ui


def source(relative):
    local = Path(__file__).resolve().parents[1]/relative
    return local if local.is_file() else Path(rm_client.__file__).resolve().parent.parent/relative


def methods(relative, class_name, names, namespace=None):
    path = source(relative)
    owner = next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.ClassDef) and n.name == class_name)
    owner.body = [n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name in names]
    owner.bases = []
    body = [ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), owner]
    ns = dict(namespace or {})
    exec(compile(ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])), str(path), 'exec'), ns)
    return ns[class_name]


class Client:
    def __init__(self):
        self.sent = []
        self.subscriptions = []
    def publish(self, topic, payload, qos):
        self.sent.append((topic, payload, qos))
        return NS(rc=0)
    def subscribe(self, topics):
        self.subscriptions.append(topics)
        return (0, 1)


class RuntimeProfileTests(unittest.TestCase):
    def setUp(self):
        self.clock = [100.]
        patcher = patch('rm_client.backend.mqtt_backend.time.perf_counter', side_effect=lambda: self.clock[0])
        patcher.start(); self.addCleanup(patcher.stop)

    def backend(self, profile=V2_PROFILE, mock=False):
        backend = RmMqttBackend(referee_profile=profile, client_id='6', mock_output=mock)
        backend.client = Client(); backend.connected = backend._subscriptions_ready = True
        backend.bind_economy_context(NS(match_mode='RMUC7v7'), NS(session=NS(
            match_mode='RMUC7v7', referee_profile=profile, robot_id='6')))
        backend.safety.configure(mock_writes=mock, allow_mqtt_publish=True, enforce_official_limits=True)
        return backend

    def receive(self, backend, name, values):
        payload = b''.join(encode_uint(number, value) for number, value in values)
        backend._on_message(backend.client, None, NS(topic=name, payload=payload))
        return payload

    def air(self, command):
        backend = self.backend()
        for name, values in [('GameStatus', [(1, 1)]), ('RobotStaticStatus', [(4,6),(5,91)]),
            ('GameStatus', [(5,4),(6,360)]), ('RobotStaticStatus', [(1,1),(2,0),(8,3)]),
            ('AirSupportStatusSync', [(1,int(command==0)),(2,30),(5,2 if command==3 else 1)]),
            ('GlobalLogisticsStatus',[(1,280)])]:
            self.receive(backend,name,values)
        return backend

    def test_opt_in_exact_identity_keeps_default_and_student(self):
        self.assertEqual(DEFAULT_PROFILE, 'rm2026-v1.3.1')
        self.assertEqual(supported_profiles(), (DEFAULT_PROFILE, STUDENT_PREVIEW_PROFILE, V2_PROFILE))
        self.assertEqual(get_profile().profile_id, DEFAULT_PROFILE)
        profile = get_profile(V2_PROFILE)
        self.assertIs(profile.codec, codec)
        self.assertEqual((profile.mqtt_host, profile.mqtt_port, profile.client_ip, profile.udp_port, profile.udp_codec),
                         ('192.168.12.1',3333,'192.168.12.2',3334,'hevc'))
        self.assertTrue(get_profile(STUDENT_PREVIEW_PROFILE).read_only)
        for name in ('rm2026-v2', 'rm2026-v2.0', 'RM2026-V2.0.0', '2.0.0', 'rm2027-v2.0.0'):
            with self.subTest(name=name), self.assertRaises(UnsupportedRefereeProfile): get_profile(name)

    def test_catalog_is_complete_with_per_action_admission(self):
        profile = get_profile(V2_PROFILE)
        self.assertEqual(len(codec.UPLINK_MESSAGES), 11)
        self.assertEqual((len(codec.DOWNLINK_MESSAGES),len(codec.DECODABLE_MESSAGES)), (25,25))
        for topic in codec.UPLINK_MESSAGES:
            self.assertTrue(profile.validate_publish(topic,1)[0])
        for qos in (True,-1,2): self.assertFalse(profile.validate_publish('AirSupportCommand',qos)[0])
        self.assertEqual(profile.available_actions(RobotState()), [])
        for topic in get_profile().codec.UPLINK_MESSAGES: self.assertTrue(get_profile().validate_publish(topic,1)[0])

    def test_all_real_paths_obey_lock_even_with_forged_intent(self):
        for entry in ('topic','named','binary','match'):
            for topic in codec.UPLINK_MESSAGES:
                with self.subTest(entry=entry,topic=topic):
                    backend=self.backend(mock=False)
                    backend.safety.update_stage(4)
                    if entry=='topic': result=backend.publish_topic(topic,b'',intent='estop_zero')[0]
                    elif entry=='named': result=backend.publish_named(topic,b'',intent='core_kmc')[0]
                    elif entry=='binary': result=backend.publish_binary(topic,b'')
                    else: result=backend.publish_match_command(topic,b'')
                    self.assertFalse(result)
                    self.assertEqual(backend.client.sent,[])
                    self.assertEqual(list(backend.publish_records),[])

    def test_dedicated_fixed_zero_stays_available_under_lock_and_estop(self):
        for estop in (False,True):
            backend=self.backend()
            if estop: backend.safety.trigger_estop()
            self.assertFalse(backend.publish_topic('KeyboardMouseControl',b'')[0])
            self.assertTrue(backend.publish_estop_zero()[0])
            self.assertEqual(backend.client.sent,[('KeyboardMouseControl',codec.encode_keyboard_mouse_control(),1)])
            self.assertEqual(backend.safety.control_state,ControlState.ESTOP if estop else ControlState.LOCKED)

    def test_registered_profile_all_four_supervised_air_commands_enqueue(self):
        for command in range(4):
            with self.subTest(command=command):
                backend=self.air(command)
                token=backend.safety.begin_qualification({'economy'},now=100.,ttl_s=30.)
                self.assertTrue(backend.publish_air_support_command(codec.encode_air_support_command(command),qualification_token=token.value))
                self.assertEqual(backend.client.sent,[('AirSupportCommand',codec.encode_air_support_command(command),1)])

    def test_registered_air_keeps_current_stage_and_token_gates(self):
        for mode in ('locked','wrong_token','prepare','stale','mock'):
            with self.subTest(mode=mode):
                backend=self.air(1)
                token=backend.safety.begin_qualification({'economy'},now=100.,ttl_s=30.)
                value=token.value
                if mode=='locked': backend.safety.lock_control('test')
                elif mode=='wrong_token': value='wrong'
                elif mode=='prepare': self.receive(backend,'GameStatus',[(5,1)])
                elif mode=='stale': self.clock[0]=103.
                else: backend.mock_output=True
                self.assertEqual(backend.publish_air_support_command(codec.encode_air_support_command(1),qualification_token=value), mode=='mock')
                self.assertEqual(backend.client.sent,[])
                self.clock[0]=100.

    def test_v2_subscribes_only_decodable_legacy_catalog_unchanged(self):
        for profile in (V2_PROFILE,DEFAULT_PROFILE,STUDENT_PREVIEW_PROFILE):
            backend=self.backend(profile)
            backend._on_connect(backend.client,None,None,0)
            actual={name for name,qos in backend.client.subscriptions[0]}
            expected=codec.DECODABLE_MESSAGES if profile==V2_PROFILE else backend.referee.codec.DOWNLINK_MESSAGES
            self.assertEqual(actual,set(expected))
            self.assertEqual(backend.client.sent,[])

    def test_malformed_radar_creates_neither_queue_nor_raw_freshness(self):
        backend=self.backend()
        self.receive(backend,'RadarInfoToClient',[(1,1)])
        self.assertEqual(backend.drain_decoded(),[])
        self.assertEqual(backend.drain_received_messages(),[])
        self.assertIsNone(backend.v2_wire_snapshot())
        feed=OfficialMatchFeed()
        result=feed.consume('RadarInfoToClient',b'',alliance='Red',local_robot_id=6,referee_profile=V2_PROFILE,received_at=100.)
        self.assertEqual(result,([],{}));self.assertEqual(feed.last_message_at,0.)

    def test_actual_callback_queue_manager_adapter_projects_selected_profile(self):
        backend=self.backend();state=RobotState(referee_profile=V2_PROFILE)
        manager_type=methods('rm_client/backend/manager.py','BackendManager',{'apply_updates','_apply_one','sync_frontend_state','_notify_referee_view'}, {'deepcopy':deepcopy,'_LOG':logging.getLogger(__name__)})
        manager=manager_type();manager.mqtt=backend;manager.safety=backend.safety
        manager._backend_transition_blocks_work=lambda:False
        manager._begin_official_state=lambda state,at:None
        manager._last_logged_stage='NOT_STARTED';manager.field_log=NS(emit=lambda *a,**kw:None)
        manager.referee=backend.referee;manager.referee_adapter=manager.referee.create_state_adapter(manager)
        manager._apply_error_count=manager._official_state_updates_count=0;manager._last_apply_error=''
        manager.referee_view_observer=None;manager._referee_view_error='';manager.stats=lambda:{}
        self.receive(backend,'GameStatus',[(1,3),(5,5),(9,0)])
        self.assertEqual(manager.apply_updates(state),1)
        self.assertEqual((state.current_round,state.current_stage,state.game_result,state.end_reason,state.settlement_round),(3,'SETTLEMENT',0,None,3))
        self.receive(backend,'GameStatus',[(10,7)])
        self.assertEqual(manager.apply_updates(state),1)
        self.assertEqual((state.game_result,state.end_reason),(0,7))
        self.assertEqual(manager._apply_error_count,0)
        self.assertEqual(backend.client.sent,[])

    def test_registered_callback_drain_reaches_live_panel_late_partial_and_disconnect(self):
        backend=self.backend();state=RobotState(referee_profile=V2_PROFILE)
        host=NS(safety=backend.safety,_last_logged_stage='NOT_STARTED',field_log=NS(emit=lambda *a,**kw:None))
        adapter=backend.referee.create_state_adapter(host)
        self.receive(backend,'RobotStaticStatus',[(4,6),(5,91)])
        self.receive(backend,'GameStatus',[(1,3),(5,5),(9,0)])
        path=source('rm_client/ui/student_panels.py');tree=ast.parse(path.read_text())
        helper=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_v2_live_rows')
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='StudentPanelRenderer')
        fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='content_rows')
        ns=dict(vars(student_ui),time=NS(perf_counter=lambda:self.clock[0]))
        exec(compile(ast.fix_missing_locations(ast.Module(body=[helper,fn],type_ignores=[])),str(path),'exec'),ns)
        frozen=(('old statistic','unchanged'),)
        window=NS(state=state,backend=NS(referee=backend.referee,mqtt=backend,scenario_key='OfficialEvent'),
                  student_ui=NS(panel='settlement',settlement=frozen))
        self.assertIn('不可用',ns['content_rows'](None,window)[0][1])
        for topic,name,data,at in backend.drain_decoded(): adapter._apply_one(state,name,data)
        rows=ns['content_rows'](None,window)
        self.assertEqual(rows[0][1],'平局');self.assertIn('未收到',rows[1][1]);self.assertEqual(rows[-1],frozen[0])
        self.receive(backend,'GameStatus',[(10,7)])
        for topic,name,data,at in backend.drain_decoded(): adapter._apply_one(state,name,data)
        self.assertEqual(ns['content_rows'](None,window)[1][1],'平局')
        backend._on_disconnect(backend.client,None)
        self.assertIn('不可用',ns['content_rows'](None,window)[0][1])
        self.assertIs(window.student_ui.settlement,frozen);self.assertEqual(backend.client.sent,[])

    def test_v2_verified_roster_events_and_student_quarantine(self):
        for profile in (V2_PROFILE,DEFAULT_PROFILE,STUDENT_PREVIEW_PROFILE):
            feed=OfficialMatchFeed()
            def deliver(health):
                payload=encode_bytes(11,bytes(health))
                return feed.consume('GlobalUnitStatus',payload,alliance='Red',local_robot_id=6,
                                    referee_profile=profile,received_at=100.)
            events,updates=deliver([100]*10)
            events,updates=deliver([100]*9+[0])
            if profile==STUDENT_PREVIEW_PROFILE:
                self.assertEqual(events,[]);self.assertNotIn('official_robot_health',updates)
            else:
                self.assertTrue(events);self.assertEqual(updates['official_robot_health'][-1],0)

    def test_legacy_offer_rejected_before_history_or_mock_mutation(self):
        bridge=EconomyCommandBridge();state=RobotState(referee_profile=V2_PROFILE)
        before=deepcopy(vars(state));offer=EconomyOffer('ammo','ammo','Buy','Buy','Test','item',1,30,1,1,True)
        for mock in (False,True):
            with self.assertRaises(ValueError): bridge.submit(state,offer,mock=mock,now=100.)
        self.assertEqual((bridge.sequence,bridge.history,bridge.last_request),(0,[],None))
        self.assertEqual(vars(state),before)

    def test_pending_legacy_transactions_retire_before_v2_mock_or_ack(self):
        offer=EconomyOffer('ammo','ammo','Buy','Buy','Test','item',1,30,1,1,True)
        for mock in (False,True):
            bridge=EconomyCommandBridge();bridge.sender=lambda request:True
            state=RobotState();transaction=bridge.submit(state,offer,mock=mock,now=100.)
            state.referee_profile=V2_PROFILE;state.economy_status_revision+=1;state.economy_command_status='succeeded'
            before=deepcopy(vars(state));self.assertIs(bridge.update(state,101.),transaction)
            self.assertEqual(transaction.status,'rejected');self.assertEqual(vars(state),before)
            self.assertEqual(bridge.history,[transaction]);self.assertEqual(transaction.completed_at,101.)

    def test_v1_mock_transaction_keeps_healthy_completion(self):
        bridge=EconomyCommandBridge();state=RobotState();state.remaining_economy=100
        offer=EconomyOffer('ammo','ammo','Buy','Buy','Test','item',1,30,1,1,True)
        transaction=bridge.submit(state,offer,mock=True,now=100.)
        bridge.update(state,101.)
        self.assertEqual(transaction.status,'succeeded');self.assertEqual(state.remaining_economy,70)

    def test_top_match_bar_actual_gate_and_context_reset(self):
        cls=methods('rm_client/ui/top_match_bar_controller.py','TopMatchBarController',{'observe_referee','_ensure_feed'}, {'TopMatchBarFeed':TopMatchBarFeed,'profiles_for_match':profiles_for_match})
        controller=cls();backend=self.backend();state=RobotState(robot_id=6,alliance_color='Red')
        controller.owner=NS(backend=NS(referee=backend.referee,mqtt=backend,scenario_key='OfficialEvent'),state=state)
        controller.enabled=lambda:True;controller.feed=None;controller._context=None;controller._custom_rosters=None
        controller._setting=lambda name,default:default;controller.renderer=NS(reset_motion=lambda:None)
        controller.reset=lambda:setattr(controller,'feed',None)
        controller.observe_referee('GameStatus',{'current_stage':4,'stage_countdown_sec':60,'__present__':frozenset({5,6})},100.)
        first=controller.feed;self.assertIsNotNone(first)
        self.assertTrue(first._values)
        backend.receive_generation+=1;controller._ensure_feed()
        self.assertIsNot(controller.feed,first);self.assertFalse(controller.feed._values)
        controller.owner.backend.referee=get_profile(STUDENT_PREVIEW_PROFILE)
        controller.observe_referee('GameStatus',{'current_stage':4,'__present__':frozenset({5})},100.)
        self.assertFalse(controller.feed._values)

    def test_v2_selector_label_is_explicit_in_both_languages(self):
        self.assertIn('preview',option_label(V2_PROFILE,False))
        self.assertIn('预览',option_label(V2_PROFILE,True))
        self.assertEqual(option_label(DEFAULT_PROFILE,False),DEFAULT_PROFILE)

    def test_unsupported_hero_mock_entry_cannot_begin_request(self):
        cls=methods('rm_client/ui/polar/mixins/video_backend_mixin.py','VideoBackendMixin',{'send_hero_deploy_request'})
        host=cls();host.backend=NS(referee=get_profile(V2_PROFILE));notes=[];host.toast=notes.append
        self.assertFalse(host.send_hero_deploy_request(1));self.assertIn('pending',notes[0])


if __name__=='__main__': unittest.main()
