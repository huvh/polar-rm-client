"""Exact form values, cancellation and context binding with inert publishers."""
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_hud_display_locale import Host
from rm_client.backend.referee.registry import get_profile, V2_PROFILE
from rm_client.ui.polar.renderers import tactical_map as tm


class EventFormTests(unittest.TestCase):
    def host(self,topic,profile='rm2026-v1.3.1'):
        h=Host('English');h.calls=[]
        method=next(e[2] for e in tm._EVENT_COMMANDS if e[1]==topic)
        h.backend=NS(referee=get_profile(profile),**{method:lambda *args,**kw:h.calls.append((args,kw)) or (True,'ok')})
        return h
    def drive(self,h,indices,integer=1,on_item=None):
        responses=iter(indices)
        def item(owner,title,prompt,choices,*args):
            i=next(responses)
            if on_item:on_item()
            return choices[i] if i is not None else '',i is not None
        with patch.object(tm.QInputDialog,'getItem',side_effect=item),patch.object(tm.QInputDialog,'getInt',return_value=(integer,True)):
            h.open_event_command_menu()

    def test_rune_has_only_activate_and_encodes_one(self):
        for profile in ('rm2026-v1.3.1',V2_PROFILE):
            h=self.host('RuneActivateCommand',profile);self.drive(h,[0,0])
            self.assertEqual(h.calls,[((1,),{})])
            self.assertEqual(h.backend.referee.codec.encode_rune_activate_command(h.calls[0][0][0]),b'\x08\x01')

    def test_dart_all_targets_and_open_values_never_confirm_launch(self):
        for profile in ('rm2026-v1.3.1',V2_PROFILE):
            for target in range(5):
                for opened in range(2):
                    h=self.host('DartCommand',profile);self.drive(h,[0,target,opened])
                    self.assertEqual(h.calls,[((target+1,bool(opened),False),{})])
                    self.assertEqual(h.backend.referee.codec.encode_dart_command(*h.calls[0][0]),bytes([8,target+1,16,opened,24,0]))

    def test_assembly_operations_zero_based_four_difficulties(self):
        for operation in range(3):
            for difficulty in range(1,5):
                h=self.host('AssemblyCommand');self.drive(h,[0,operation],difficulty)
                self.assertEqual(h.calls,[((operation,difficulty),{})])
                self.assertEqual(h.backend.referee.codec.encode_assembly_command(*h.calls[0][0]),bytes([8,operation,16,difficulty]))

    def test_invalid_assembly_difficulty_is_not_coerced(self):
        for value in (0,5,True,'1',float('inf')):
            h=self.host('AssemblyCommand');self.drive(h,[0,0],value)
            self.assertEqual(h.calls,[])

    def test_v1_sentry_only_documented_one_through_nine(self):
        for index in range(9):
            h=self.host('SentryCtrlCommand');self.drive(h,[0,index])
            self.assertEqual(h.calls,[((index+1,),{})])

    def test_v2_sentry_uses_economic_confirmation_not_direct_publisher(self):
        from rm_client.ui.polar.renderers import v2_economy_dialog as ed
        h=self.host('SentryCtrlCommand',V2_PROFILE)
        with patch.object(ed,'_open_v2_economy_dialog') as dialog:self.drive(h,[0]);dialog.assert_called_once_with(h,'SentryCtrlCommand')
        self.assertEqual(h.calls,[])

    def test_cancellation_at_each_dart_step_emits_nothing(self):
        for step in range(3):
            h=self.host('DartCommand');self.drive(h,[0]*step+[None])
            self.assertEqual(h.calls,[]);self.assertEqual(h.toasts,[])

    def test_context_change_during_final_input_emits_nothing(self):
        h=self.host('DartCommand');count=[0]
        def mutate():
            count[0]+=1
            if count[0]==3:h.state.current_round+=1
        self.drive(h,[0,0,0],on_item=mutate)
        self.assertEqual(h.calls,[])
        self.assertIn('context changed',h.toasts[-1])

    def test_unknown_returned_label_cannot_coerce_to_other_operation(self):
        h=self.host('RuneActivateCommand')
        with patch.object(tm.QInputDialog,'getItem',side_effect=lambda o,t,p,c,*args:(c[0],True) if t=='Event commands' else ('0 = cancel',True)):
            h.open_event_command_menu()
        self.assertEqual(h.calls,[])

    def test_menu_uses_reviewed_capability_and_present_publisher(self):
        h=self.host('DartCommand',V2_PROFILE)
        h.backend.referee=NS(profile_id=V2_PROFILE,validate_publish=lambda topic,qos:(False,'unreviewed'))
        with patch.object(tm.QInputDialog,'getItem') as item:h.open_event_command_menu();item.assert_not_called()
        self.assertEqual(h.calls,[])

    def test_performance_menu_role_is_version_specific(self):
        for profile,role,allowed in ((V2_PROFILE,6,True),(V2_PROFILE,7,False),('rm2026-v1.3.1',7,True)):
            h=self.host('RobotPerformanceSelectionCommand',profile);h.state.robot_id=role
            self.assertEqual(bool(tm._event_command_options(h)),allowed)

    def test_blue_aerial_hint_is_not_dart_client_identity(self):
        h=self.host('DartCommand',V2_PROFILE);h.state.robot_id=106
        labels=[]
        with patch.object(tm.QInputDialog,'getItem',side_effect=lambda o,t,p,c,*args:labels.append(p) or (c[0],True)):
            h.open_event_command_menu()
        self.assertIn('Aerial operator: same-team dart target',labels)
        self.assertEqual(h.calls,[((1,False,False),{})])


if __name__=='__main__':unittest.main()
