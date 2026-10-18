"""Inert delivery of actual Economy/ClickGUI method AST; no Qt/facade imports."""
import ast
from enum import Enum
from pathlib import Path
from types import MethodType, SimpleNamespace as NS
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import rm_client
REPO = Path(rm_client.__file__).resolve().parent.parent
from rm_client.ui.overlay_coordinator import OverlayCoordinator, OverlayKind
ECONOMY_SOURCE = REPO/'rm_client/ui/polar/mixins/economy_mixin.py'
CLICKGUI_SOURCE = REPO/'rm_client/ui/polar/mixins/clickgui_builders_mixin.py'
PRIMITIVES_SOURCE = REPO/'rm_client/ui/polar/primitives.py'


def method(source, owner, name, scope):
    cls = next(n for n in ast.parse(source.read_text(encoding='utf-8-sig')).body if isinstance(n,ast.ClassDef) and n.name==owner)
    node = next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name==name)
    module = ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),node],type_ignores=[])
    exec(compile(ast.fix_missing_locations(module),str(source),'exec'),scope)
    return scope[name]


def phase_type():
    node=next(n for n in ast.parse(PRIMITIVES_SOURCE.read_text()).body if isinstance(n,ast.ClassDef) and n.name=='EconomyScenePhase')
    scope={'Enum':Enum}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),str(PRIMITIVES_SOURCE),'exec'),scope)
    return scope['EconomyScenePhase']


PHASE = phase_type()


def fixture():
    callbacks=[]
    host=NS(trace=[],callbacks=callbacks,gui_visible=False,home_visible=False,
            economy_phase=PHASE.CLOSED,economy_visible=False,_economy_generation=0,
            _economy_closing_generation=None,_economy_restore_pending_generation=None,
            _economy_pending_overlay=None,_economy_scene_epoch=0,_economy_close_finalized=True,
            economy_category='ammo',economy_selected_key='',economy_selected=0,
            economy_armed_key='',economy_hold_key='',_economy_hold_input_owner=None,
            hotspots=[],hero_deploy_ui=NS(visible=False),_student_pending_panel=None)
    def record(name):
        return lambda *args,**kwargs:host.trace.append(name)
    def queue(delay,callback):
        assert delay==0
        callbacks.append(callback)
    scope={'time':NS(perf_counter=lambda:10.),'QTimer':NS(singleShot=queue),'QRectF':lambda:None,
           'EconomyScenePhase':PHASE,'OverlayKind':OverlayKind,'PRIMARY_GUI_MODE':'Jello Sigma'}
    for name in ['open_economy_workspace','close_economy_workspace','_finalize_economy_restore']:
        setattr(host,name,MethodType(method(ECONOMY_SOURCE,'EconomyMixin',name,scope),host))
    host.set_clickgui_visible=MethodType(method(CLICKGUI_SOURCE,'ClickGuiBuildersMixin','set_clickgui_visible',scope),host)
    host.overlay_coordinator=OverlayCoordinator(on_input_claimed=record('input-claimed'))
    host.close_student_panel=record('close-student')
    host.hero_deploy_video_cut_active=lambda:False
    host.open_hero_deploy_interface=record('open-hero')
    host.close_hero_deploy_interface=record('close-hero')
    host.close_match_chat=record('close-chat')
    host.open_match_chat=record('open-chat')
    host.open_student_panel=lambda panel:host.trace.append(('open-student',panel))
    host.cancel_quick_action_wheel=record('cancel-radial')
    host.economy_offers=lambda *args:[]
    host.economy_categories=lambda *args:['ammo']
    host.reconcile_economy_selection=lambda:None
    host.economy_island=NS(progress=0.,target=0.,velocity=0.,set_target=record('economy-target'))
    for name in ['economy_category_scroll','economy_offers_scroll','economy_detail_scroll']:
        setattr(host,name,NS(position=0.,target=0.,velocity=0.))
    host.anim_duration=lambda value:value
    host.invalidate_transient_overlay_scene=record('invalidate')
    host.play_gui_transition_sound=record('sound')
    host.frame_scheduler=NS(force=record('frame-force'))
    host.update=record('update')
    host.pointer_interaction=NS(cancel_epoch=record('cancel-pointer'))
    host.jello_state=NS(legacy_mode=None,begin_session=record('jello-session'),request_reset=record('jello-reset'))
    host.mode_manager=NS(set_mode=record('mode'))
    host.gui_timeline=NS(set_target=record('gui-target'))
    host.active_clickgui_mode=lambda:'Jello Sigma'
    host.toast=record('toast')
    return host


def queue_clickgui(host):
    host.open_economy_workspace('ammo')
    host.set_clickgui_visible(True,announce=False,play_sound=False)
    generation=host._economy_generation
    assert host.economy_phase==PHASE.CLOSING
    assert host._economy_pending_overlay==OverlayKind.CLICKGUI
    host._economy_restore_pending_generation=generation
    host._finalize_economy_restore(generation)
    assert host.economy_phase==PHASE.CLOSED
    assert len(host.callbacks)==1
    return generation


def deliver(host):
    callback=host.callbacks.pop(0)
    callback()


class EconomyDeferredOverlayEpochTests(unittest.TestCase):
    def test_current_generation_executes_queued_clickgui_once(self):
        host=fixture(); generation=queue_clickgui(host)
        self.assertFalse(host.gui_visible)
        deliver(host)
        self.assertTrue(host.gui_visible)
        self.assertEqual(host.overlay_coordinator.modal,OverlayKind.CLICKGUI)
        self.assertEqual(host._economy_generation,generation)
        self.assertEqual(host.trace.count('jello-session'),1)
        self.assertEqual(host.callbacks,[])

    def test_fresh_economy_open_invalidates_old_queued_clickgui(self):
        host=fixture(); old=queue_clickgui(host)
        host.open_economy_workspace('ammo')
        generation=host._economy_generation
        self.assertGreater(generation,old)
        self.assertIsNone(host._economy_pending_overlay)
        before=list(host.trace)
        deliver(host)
        self.assertEqual(host.economy_phase,PHASE.OPENING,'old callback must not close the newly opened economy session')
        self.assertTrue(host.economy_visible)
        self.assertEqual(host._economy_generation,generation)
        self.assertIsNone(host._economy_pending_overlay)
        self.assertEqual(host.overlay_coordinator.modal,OverlayKind.ECONOMY)
        self.assertEqual(host.trace,before)

    def test_newer_close_and_finalize_remains_deliverable(self):
        host=fixture(); queue_clickgui(host)
        host.open_economy_workspace('ammo')
        host.set_clickgui_visible(True,announce=False,play_sound=False)
        generation=host._economy_generation
        host._economy_restore_pending_generation=generation
        host._finalize_economy_restore(generation)
        self.assertEqual(len(host.callbacks),2)
        deliver(host)
        self.assertFalse(host.gui_visible,'old callback may not consume the newer intent')
        self.assertEqual(len(host.callbacks),1)
        deliver(host)
        self.assertTrue(host.gui_visible)
        self.assertEqual(host.overlay_coordinator.modal,OverlayKind.CLICKGUI)
        self.assertEqual(host.trace.count('jello-session'),1)

    def test_no_pending_overlay_schedules_nothing(self):
        host=fixture(); host.open_economy_workspace(); host.close_economy_workspace()
        generation=host._economy_generation
        host._economy_restore_pending_generation=generation
        host._finalize_economy_restore(generation)
        self.assertEqual(host.economy_phase,PHASE.CLOSED)
        self.assertEqual(host.callbacks,[])
        self.assertIsNone(host.overlay_coordinator.modal)

    def test_stale_finalize_keeps_new_scene_and_schedules_nothing(self):
        host=fixture(); host.open_economy_workspace(); host.close_economy_workspace()
        old=host._economy_generation
        host.open_economy_workspace()
        host._economy_restore_pending_generation=old
        before=list(host.trace)
        host._finalize_economy_restore(old)
        self.assertEqual(host.trace,before)
        self.assertEqual(host.economy_phase,PHASE.OPENING)
        self.assertEqual(host.callbacks,[])
        self.assertEqual(host.overlay_coordinator.modal,OverlayKind.ECONOMY)

    def test_current_generation_delivers_each_supported_overlay(self):
        for kind in [OverlayKind.CLICKGUI,OverlayKind.CHAT,OverlayKind.HERO_DEPLOY,OverlayKind.STUDENT]:
            with self.subTest(kind=kind):
                host=fixture(); host.open_economy_workspace(); host.close_economy_workspace()
                generation=host._economy_generation
                host._economy_pending_overlay=kind
                host._student_pending_panel='inventory'
                host._economy_restore_pending_generation=generation
                host._finalize_economy_restore(generation)
                self.assertEqual(len(host.callbacks),1)
                deliver(host)
                expected={OverlayKind.CLICKGUI:'jello-session',OverlayKind.CHAT:'open-chat',
                          OverlayKind.HERO_DEPLOY:'open-hero',OverlayKind.STUDENT:('open-student','inventory')}[kind]
                self.assertEqual(host.trace.count(expected),1)
                self.assertEqual(host.callbacks,[])
                self.assertIsNone(host._economy_pending_overlay)
                if kind==OverlayKind.STUDENT:self.assertIsNone(host._student_pending_panel)

    def test_new_generation_cancels_each_old_overlay_without_consuming_new_student_intent(self):
        for kind in [OverlayKind.CLICKGUI,OverlayKind.CHAT,OverlayKind.HERO_DEPLOY,OverlayKind.STUDENT]:
            with self.subTest(kind=kind):
                host=fixture(); host.open_economy_workspace(); host.close_economy_workspace()
                host._economy_pending_overlay=kind
                host._student_pending_panel='old-panel'
                generation=host._economy_generation
                host._economy_restore_pending_generation=generation
                host._finalize_economy_restore(generation)
                host.open_economy_workspace()
                # New-generation intent belongs to the new session, never the old closure.
                host._student_pending_panel='new-panel'
                before=dict(vars(host)); trace=list(host.trace)
                deliver(host)
                self.assertEqual(host.trace,trace)
                self.assertEqual(host.economy_phase,PHASE.OPENING)
                self.assertEqual(host._economy_generation,before['_economy_generation'])
                self.assertEqual(host._student_pending_panel,'new-panel')
                self.assertIsNone(host._economy_pending_overlay)

    def test_old_callback_does_not_requeue_over_new_close_in_progress(self):
        host=fixture(); queue_clickgui(host)
        host.open_economy_workspace()
        host._economy_pending_overlay=OverlayKind.CHAT
        host.close_economy_workspace()
        generation=host._economy_generation
        before=list(host.trace)
        deliver(host)
        self.assertEqual(host.trace,before)
        self.assertEqual(host.economy_phase,PHASE.CLOSING)
        self.assertEqual(host._economy_generation,generation)
        self.assertEqual(host._economy_pending_overlay,OverlayKind.CHAT)
        host._economy_restore_pending_generation=generation
        host._finalize_economy_restore(generation)
        deliver(host)
        self.assertEqual(host.trace.count('open-chat'),1)
        self.assertFalse(host.gui_visible)

    def test_current_callback_failure_keeps_existing_propagation_and_no_retry(self):
        for failure in [ValueError('overlay failed'),KeyboardInterrupt('process control')]:
            with self.subTest(kind=type(failure).__name__):
                host=fixture(); queue_clickgui(host)
                def fail(*args,**kwargs):raise failure
                host.toast=fail
                with self.assertRaises(type(failure)) as caught:deliver(host)
                self.assertIs(caught.exception,failure)
                self.assertTrue(host.gui_visible)
                self.assertEqual(host.overlay_coordinator.modal,OverlayKind.CLICKGUI)
                self.assertEqual(host.callbacks,[])
                self.assertIsNone(host._economy_pending_overlay)

if __name__=='__main__':unittest.main(verbosity=2)
