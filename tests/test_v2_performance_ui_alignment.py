"""Preparation-only mode confirmation, including post-token observer mutation."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace as NS
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_v2_economy_ui_alignment import host_fixture, update
from rm_client.backend.manager import BackendManager
from rm_client.ui.polar.renderers import tactical_map as tm


class PerformanceDialogTests(unittest.TestCase):
    def fixture(self):
        h=host_fixture(6,1)
        h.registry.get('RobotProfile').get_setting('Role').value='Aerial'
        h.registry.get('RobotProfile').get_setting('Sentinel Control').value='SemiAuto'
        h.backend.performance_values=BackendManager.performance_values
        h.tokens=[]
        h.backend.begin_qualification=lambda caps,**kw:h.tokens.append((caps,kw)) or NS(value='mode-token')
        h.backend.publish_robot_performance=lambda *args,**kw:h.calls.append((args,kw)) or (True,'ok')
        return h
    def drive(self,h,question=None):
        with patch.object(tm.time,'perf_counter',return_value=100.),patch.object(tm.QMessageBox,'question',side_effect=question or (lambda *a:tm.QMessageBox.StandardButton.Yes)):
            tm._open_v2_sentry_control_dialog(h)

    def test_one_explicit_request_gets_core_token_and_locks(self):
        h=self.fixture();self.drive(h)
        self.assertEqual(h.tokens,[({'core_kmc'},{'ttl_s':15.})])
        self.assertEqual(h.calls,[((0,0,1),{'qualification_token':'mode-token'})])
        self.assertEqual(h.locks,[True]);self.assertIsNone(h._economy_qualification_token)

    def test_cancel_invalid_phase_and_changed_selection_emit_nothing(self):
        h=self.fixture();self.drive(h,lambda *a:tm.QMessageBox.StandardButton.No)
        self.assertEqual(h.calls+h.tokens+h.locks,[])
        h=self.fixture();update(h,'GameStatus','current_stage',4);self.drive(h)
        self.assertEqual(h.calls+h.tokens,[])
        h=self.fixture()
        def mutate(*args):
            h.registry.get('RobotProfile').get_setting('Sentinel Control').value='Automatic'
            return tm.QMessageBox.StandardButton.Yes
        self.drive(h,mutate);self.assertEqual(h.calls+h.tokens,[])

    def test_begin_observer_identity_round_session_or_values_change_cancels_and_locks(self):
        for kind in ('client','round','session','selection'):
            h=self.fixture()
            def begin(*args,**kwargs):
                h.tokens.append(True)
                if kind=='client':h.backend.mqtt.client_id='106'
                elif kind=='round':update(h,'GameStatus','current_round',2)
                elif kind=='session':h.backend.qualification.session=NS(**vars(h.backend.qualification.session))
                else:h.registry.get('RobotProfile').get_setting('Sentinel Control').value='Automatic'
                return NS(value='mode-token')
            h.backend.begin_qualification=begin;self.drive(h)
            self.assertEqual(h.calls,[],(kind,h.toasts))
            self.assertEqual(len(h.tokens),1);self.assertEqual(h.locks,[True])

    def test_publish_rejection_or_error_does_not_retry_and_always_locks(self):
        for fail in (False,True):
            h=self.fixture()
            def publish(*args,**kwargs):
                h.calls.append((args,kwargs))
                if fail:raise RuntimeError('injected')
                return False,'rejected'
            h.backend.publish_robot_performance=publish;self.drive(h)
            self.assertEqual(len(h.calls),1);self.assertEqual(h.locks,[True])


if __name__=='__main__':unittest.main()
