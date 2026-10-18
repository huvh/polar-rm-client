"""Actual preview, acceptance and close-admission AST with inert collaborators."""
import ast
from dataclasses import dataclass
from pathlib import Path
import sys
from types import MethodType, SimpleNamespace as NS
import unittest

R=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(R))
import rm_client
R=Path(rm_client.__file__).resolve().parent.parent
from rm_client.ui.polar.window_lifecycle import WindowLifecycleController, OwnerAction
from rm_client.lifecycle import TeardownTask
CONFIG_SOURCE=R/'rm_client/ui/polar/mixins/config_actions_mixin.py'
VIDEO_SOURCE=R/'rm_client/ui/polar/mixins/video_backend_mixin.py'
WINDOW_SOURCE=R/'rm_client/ui/polar_app.py'
EVENT_SOURCE=R/'rm_client/combat_events.py'


def node(relative, owner, name):
    source={
        'preview_elimination_fx':CONFIG_SOURCE,
        'accept_combat_event':VIDEO_SOURCE,
        '_begin_window_shutdown':WINDOW_SOURCE,
        'CombatEvent':EVENT_SOURCE,
    }[name]
    tree=ast.parse(source.read_text(encoding='utf-8-sig'))
    if owner:
        tree=next(item for item in tree.body if isinstance(item,ast.ClassDef) and item.name==owner)
    return next(item for item in tree.body if isinstance(item,(ast.FunctionDef,ast.ClassDef)) and item.name==name)


def compile_node(selected, scope):
    tree=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),selected],type_ignores=[])
    exec(compile(ast.fix_missing_locations(tree),'<actual-source-method>','exec'),scope)
    return scope[selected.name]


CombatEvent=compile_node(node('rm_client/combat_events.py',None,'CombatEvent'),{'dataclass':dataclass,'__name__':__name__})


def host():
    h=NS(trace=[],callbacks=[],sound_closed=False,enabled=True,now=100.0)
    def record(name):
        return lambda *args,**kwargs:h.trace.append((name,args))
    def enqueue(delay,callback):h.callbacks.append((delay,callback))
    scope={'time':NS(perf_counter=lambda:h.now),'QTimer':NS(singleShot=enqueue),
           'CombatEvent':CombatEvent,'OwnerAction':OwnerAction,'TeardownTask':TeardownTask}
    for path,owner,name in (
        ('rm_client/ui/polar/mixins/config_actions_mixin.py','ConfigActionsMixin','preview_elimination_fx'),
        ('rm_client/ui/polar/mixins/video_backend_mixin.py','VideoBackendMixin','accept_combat_event'),
        ('rm_client/ui/polar_app.py','PolarRMWindow','_begin_window_shutdown'),
    ):
        setattr(h,name,MethodType(compile_node(node(path,owner,name),scope),h))
    effect=NS(enabled=True)
    h.registry=NS(get=lambda name:effect if name=='EliminationFX' else None)
    h.setting_mode=lambda module,key,default:default
    h.setting_bool=lambda module,key,default:default
    h.get_setting_number=lambda module,key,default:default
    h.elimination_element_toggles=lambda effect:{}
    h.state=NS(visual_kill_count=0,referee_kill_count=0,kill_streak=0,push_event=record('event'))
    def close_audio():
        h.sound_closed=True
        h.trace.append(('audio-close',()))
    def trigger(event,**kwargs):h.trace.append(('renderer-trigger',(event.victim_id,h.sound_closed)))
    h.kill_fx=NS(sounds=NS(close=close_audio,wait_closed=record('audio-wait')),trigger=trigger)
    h.backend=NS(request_shutdown=lambda **kwargs:h.trace.append(('shutdown-request',tuple(task.name for task in kwargs['teardown_tasks']))))
    h._window_lifecycle=WindowLifecycleController(h.backend)
    for name in ('camera_worker','local_vision','tongji_receiver','tongji_bridge'):
        setattr(h,name,NS(close=record(name+'-close')))
    h.startup_wallpaper=NS(video_player=NS(close=record('video-close')),close_thumbnail_workers=record('thumbnail-close'))
    h._gpu_prewarm_timer=NS(stop=record('warmup-stop'))
    def enabled(value):h.enabled=value; h.trace.append(('enabled',(value,)))
    h.setEnabled=enabled
    h._clear_control_inputs_for_lock=record('input-clear')
    h.cancel_pending_configuration_for_close=record('configuration-cancel')
    h.timer=NS(start=record('main-timer-start'))
    h.update=record('update')
    return h


def deliver(h):
    delay,callback=h.callbacks.pop(0)
    h.now=100.+delay/1000.
    callback()


class DeferredPreviewCloseTests(unittest.TestCase):
    def test_active_sequence_delivers_all_six_original_requests(self):
        h=host(); h.preview_elimination_fx()
        self.assertEqual([delay for delay,_ in h.callbacks],[0,650,1300,1950,2600,3250])
        while h.callbacks:deliver(h)
        self.assertEqual(h.state.referee_kill_count,6)
        self.assertEqual(h.state.kill_streak,6)
        self.assertEqual([row for row in h.trace if row[0]=='renderer-trigger'],
                         [('renderer-trigger',(101+i,False)) for i in range(6)])

    def test_close_admission_retires_remaining_queued_preview_runtime(self):
        h=host(); h.preview_elimination_fx(); deliver(h)
        self.assertEqual(h.state.referee_kill_count,1)
        h._begin_window_shutdown()
        self.assertTrue(h._window_lifecycle.closing)
        self.assertFalse(h.enabled)
        self.assertTrue(h.sound_closed)
        before=(h.state.referee_kill_count,h.state.kill_streak,list(h.trace))
        while h.callbacks:deliver(h)
        after=(h.state.referee_kill_count,h.state.kill_streak,list(h.trace))
        self.assertEqual(after,before,'queued preview must not restart normal presentation work after close admission')

    def test_active_callback_preserves_ordinary_and_process_control_failure_identity(self):
        for failure in (ValueError('renderer'),SystemExit('renderer')):
            with self.subTest(kind=type(failure).__name__):
                h=host(); h.preview_elimination_fx()
                def fail(*args,**kwargs):raise failure
                h.kill_fx.trigger=fail
                with self.assertRaises(type(failure)) as caught:deliver(h)
                self.assertIs(caught.exception,failure)
                self.assertEqual(h.state.referee_kill_count,1)
                self.assertEqual(h.state.kill_streak,1)
                self.assertEqual(len(h.callbacks),5)

    def test_close_before_first_delivery_rejects_every_queued_event(self):
        h=host(); h.preview_elimination_fx(); h._begin_window_shutdown()
        before=(vars(h.state).copy(),list(h.trace))
        while h.callbacks:deliver(h)
        self.assertEqual((vars(h.state),h.trace),before)
        self.assertFalse(hasattr(h,'dynamic_island_last_event'))

    def test_close_after_each_middle_position_preserves_accepted_prefix(self):
        for accepted in (1,3,5):
            with self.subTest(accepted=accepted):
                h=host(); h.preview_elimination_fx()
                for _ in range(accepted):deliver(h)
                self.assertEqual(h.state.referee_kill_count,accepted)
                self.assertTrue(hasattr(h,'dynamic_island_event_started'))
                h._begin_window_shutdown()
                before=(vars(h.state).copy(),list(h.trace),h.dynamic_island_event_started)
                while h.callbacks:deliver(h)
                self.assertEqual((vars(h.state),h.trace,h.dynamic_island_event_started),before)
                self.assertEqual(h.state.referee_kill_count,accepted)

    def test_delivery_checks_current_lifecycle_instead_of_scheduling_snapshot(self):
        h=host(); h.preview_elimination_fx()
        h._window_lifecycle=NS(closing=True)
        while h.callbacks:deliver(h)
        self.assertEqual(h.state.referee_kill_count,0)
        self.assertEqual(h.trace,[])

    def test_standalone_host_without_lifecycle_keeps_existing_preview_behavior(self):
        for absent in (True,False):
            with self.subTest(absent=absent):
                h=host()
                if absent:del h._window_lifecycle
                else:h._window_lifecycle=None
                h.preview_elimination_fx()
                while h.callbacks:deliver(h)
                self.assertEqual(h.state.referee_kill_count,6)
                self.assertEqual(len([row for row in h.trace if row[0]=='renderer-trigger']),6)

    def test_lifecycle_attached_after_scheduling_still_blocks_close_delivery(self):
        h=host(); del h._window_lifecycle; h.preview_elimination_fx()
        h._window_lifecycle=NS(closing=True)
        while h.callbacks:deliver(h)
        self.assertEqual(h.state.referee_kill_count,0)
        self.assertEqual(h.trace,[])

    def test_single_and_all_kill_types_preserve_payload_and_queue_order(self):
        for single,sequence,types in (
            (True,'All Kill Types',['NORMAL']),
            (False,'All Kill Types',['NORMAL','HEADSHOT','EXPLOSION','CRIT','ASSIST','DESTROY_VEHICLE']),
        ):
            with self.subTest(single=single):
                h=host(); h.setting_mode=lambda module,key,default:sequence if key=='Preview Sequence' else default
                seen=[]; h.accept_combat_event=seen.append
                h.preview_elimination_fx(single=single)
                self.assertEqual([delay for delay,_ in h.callbacks],[650*i for i in range(len(types))])
                while h.callbacks:deliver(h)
                self.assertEqual([e.kill_type for e in seen],types)
                self.assertEqual([e.combo for e in seen],list(range(1,len(types)+1)))
                self.assertEqual([e.victim_id for e in seen],list(range(101,101+len(types))))
                self.assertTrue(all(e.source=='preview' and e.detail=='local_preview' and e.timestamp==100.0 for e in seen))

    def test_open_delivery_still_uses_current_effect_settings(self):
        h=host(); h.preview_elimination_fx()
        h.registry.get('EliminationFX').enabled=False
        while h.callbacks:deliver(h)
        self.assertEqual(h.state.referee_kill_count,6)
        self.assertFalse(any(row[0]=='renderer-trigger' for row in h.trace))

    def test_already_closing_host_cannot_resume_runtime_through_public_preview(self):
        h=host(); h._begin_window_shutdown(); before=list(h.trace)
        h.preview_elimination_fx()
        self.assertEqual(len(h.callbacks),6)
        while h.callbacks:deliver(h)
        self.assertEqual(h.trace,before)
        self.assertEqual(h.state.referee_kill_count,0)


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(DeferredPreviewCloseTests))
    blocked=[name for name in sys.modules if name.startswith(('PySide6','OpenGL','rm_client.ui.polar_app',
                                                             'rm_client.backend.manager','rm_client.auto_spin'))]
    assert not blocked,blocked
    print('No native/facade/manager/spin imports; all delivery and resource collaborators are inert.')
    sys.exit(not result.wasSuccessful())
