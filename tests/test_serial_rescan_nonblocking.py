"""Actual deferred rescan adapter keeps all discovery on the snapshot route."""
from __future__ import annotations
import ast
from contextlib import ExitStack, contextmanager
from pathlib import Path
import sys
from types import MethodType, SimpleNamespace as NS
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import rm_client
from rm_client import serial_ports as sp
R=Path(rm_client.__file__).resolve().parent.parent


def rescan_method(h):
    source=R/'rm_client/ui/polar/mixins/config_actions_mixin.py'
    tree=ast.parse(source.read_text(encoding='utf-8-sig'))
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ConfigActionsMixin')
    selected=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='rescan_serial_ports')
    scope={'QTimer':NS(singleShot=lambda delay,callback:h.callbacks.append((delay,callback)))}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[selected],type_ignores=[])),str(source),'exec'),scope)
    return MethodType(scope['rescan_serial_ports'],h)


def host(*,angles=True,robot=True):
    settings={name:NS(value=value,options=[value]) for name,value in
              (('Port','Auto'),('DT7 Port','Auto'),('CC Port','Auto'),
               ('Angle RX Port','ABSENT_RX'),('Angle TX Port','ABSENT_TX'))}
    modules={}
    if robot:modules['RobotLink']=NS(get_setting=lambda name:settings.get(name))
    if angles:modules['ControllerAngles']=NS(get_setting=lambda name:settings.get(name))
    h=NS(callbacks=[],trace=[],settings=settings,registry=NS(get=modules.get),
         control=NS(dt7_link=NS(release_pending=False),cc_link=NS(release_pending=False)))
    h.toast=lambda text:h.trace.append(('toast',text))
    h.auto_save_config=lambda:h.trace.append(('auto-save',))
    h.rescan_serial_ports=rescan_method(h)
    return h


@contextmanager
def discovery_fixture():
    clock=[100.0]; workers=[]; scans=[]
    entries=[{'device':'NEW','description':'DJI','vid':0xFFF0,'pid':0x0008}]
    class QueuedWorker:
        ident=None
        def __init__(self,*,target,name,daemon):self.target=target; workers.append(self)
        def start(self):pass
    def scan():scans.append(True); return [dict(entry) for entry in entries]
    with ExitStack() as stack:
        for name,value in (('_port_cache',[]),('_port_cache_at',float('-inf')),
                           ('_port_refresh_running',False),('_port_cache_generation',0)):
            stack.enter_context(patch.object(sp,name,value))
        stack.enter_context(patch.object(sp.time,'monotonic',side_effect=lambda:clock[0]))
        stack.enter_context(patch.object(sp.threading,'Thread',QueuedWorker))
        stack.enter_context(patch.object(sp,'_scan_serial_ports',side_effect=scan))
        yield NS(clock=clock,workers=workers,scans=scans,entries=entries)
        for worker in workers:worker.target()


class SerialRescanNonblockingTests(unittest.TestCase):
    def setUp(self):
        guard=patch.object(sp,'_scan_serial_ports',side_effect=AssertionError('physical discovery is forbidden in this suite'))
        guard.start(); self.addCleanup(guard.stop)

    def test_nonblocking_keyword_reaches_every_robot_and_angle_choice(self):
        h=host(); calls=[]
        def choices(*,nonblocking=False):calls.append(nonblocking); return ['Stub','Auto','NEW']
        with patch.object(sp,'port_choices',side_effect=choices),patch.object(sp,'rc_port_choices',side_effect=choices):
            sp.refresh_port_options(h.registry,nonblocking=True)
        self.assertEqual(calls,[True]*4)

    def test_default_and_explicit_false_preserve_synchronous_api(self):
        for explicit in (False,True):
            with self.subTest(explicit=explicit):
                h=host(); calls=[]
                def choices(*,nonblocking=False):calls.append(nonblocking); return ['Stub','Auto','NEW']
                with patch.object(sp,'port_choices',side_effect=choices),patch.object(sp,'rc_port_choices',side_effect=choices):
                    sp.refresh_port_options(h.registry,**({'nonblocking':False} if explicit else {}))
                self.assertEqual(calls,[False]*4)

    def test_requested_keyword_is_forwarded_without_bool_coercion(self):
        h=host(); marker=object(); seen=[]
        def choices(*,nonblocking=False):seen.append(nonblocking); return ['Stub','Auto']
        with patch.object(sp,'port_choices',side_effect=choices),patch.object(sp,'rc_port_choices',side_effect=choices):
            sp.refresh_port_options(h.registry,nonblocking=marker)
        self.assertEqual(len(seen),4); self.assertTrue(all(value is marker for value in seen))

    def test_actual_callback_after_cache_expiry_uses_snapshot_without_sync_scan(self):
        h=host()
        with discovery_fixture() as d:
            h.rescan_serial_ports(); d.workers[0].target()
            self.assertFalse(sp.discovery_pending()); self.assertEqual(len(d.scans),1)
            d.clock[0]+=2.0
            with patch.object(sp,'_scan_serial_ports',side_effect=AssertionError('UI callback entered synchronous discovery')):
                delay,callback=h.callbacks.pop(0); callback()
            self.assertEqual(delay,50); self.assertEqual(len(d.workers),2)
            self.assertTrue(sp.discovery_pending()); self.assertEqual(len(d.scans),1)
            self.assertEqual(h.settings['Angle RX Port'].options,['Stub','COM1','COM3','COM5','NEW','ABSENT_RX'])
            self.assertEqual(h.settings['Angle RX Port'].value,'ABSENT_RX')
            self.assertEqual(h.trace[-1],('auto-save',))

    def test_actual_callback_after_cache_invalidation_uses_snapshot(self):
        h=host()
        with discovery_fixture() as d:
            h.rescan_serial_ports(); d.workers[0].target(); sp.invalidate_port_cache()
            with patch.object(sp,'_scan_serial_ports',side_effect=AssertionError('UI callback rescanned invalidated cache')):
                h.callbacks.pop(0)[1]()
            self.assertEqual(len(d.workers),2); self.assertEqual(len(d.scans),1)
            self.assertTrue(sp.discovery_pending())

    def test_pending_scan_poll_keeps_options_and_reschedules_same_callback(self):
        h=host()
        with discovery_fixture() as d:
            before={name:(s.value,list(s.options)) for name,s in h.settings.items()}
            h.rescan_serial_ports(); delay,callback=h.callbacks.pop(0); callback()
            self.assertEqual(h.callbacks,[(50,callback)])
            self.assertEqual({name:(s.value,list(s.options)) for name,s in h.settings.items()},before)
            self.assertEqual(len(h.trace),1); self.assertEqual(len(d.workers),1)
            d.workers[0].target(); h.callbacks.pop(0)[1]()
            self.assertEqual(h.callbacks,[]); self.assertEqual(h.trace[-1],('auto-save',))

    def test_healthy_completion_preserves_values_diffs_and_neutral_retry_order(self):
        h=host(); h.settings['Angle TX Port'].value='Auto'
        h.control.dt7_link=NS(release_pending=True,retry_release=lambda:h.trace.append(('dt7-neutral',)))
        h.control.cc_link=NS(release_pending=True,retry_release=lambda:h.trace.append(('cc-neutral',)))
        with discovery_fixture() as d:
            h.rescan_serial_ports(); d.workers[0].target(); h.callbacks.pop(0)[1]()
            self.assertEqual(len(d.scans),1)
        self.assertEqual([row[0] for row in h.trace],['toast','dt7-neutral','cc-neutral','toast','auto-save'])
        self.assertIn('Angle RX Port:',h.trace[-2][1])
        self.assertEqual(h.settings['Angle TX Port'].value,'Auto')
        self.assertNotIn('Auto',h.settings['Angle TX Port'].options)
        self.assertIn('ABSENT_RX',h.settings['Angle RX Port'].options)
        self.assertEqual(h.settings['Port'].value,'Auto')

    def test_missing_angle_or_robot_modules_keep_existing_scope(self):
        for angles,robot,expected in ((False,True,3),(True,False,0)):
            with self.subTest(angles=angles,robot=robot):
                h=host(angles=angles,robot=robot); seen=[]
                def choices(*,nonblocking=False):seen.append(nonblocking); return ['Auto']
                with patch.object(sp,'port_choices',side_effect=choices),patch.object(sp,'rc_port_choices',side_effect=choices):
                    diffs=sp.refresh_port_options(h.registry,nonblocking=True)
                self.assertEqual(seen,[True]*expected)
                if not robot:self.assertEqual(diffs,[])

    def test_snapshot_failure_retains_identity_and_existing_partial_update_order(self):
        for failure in (ValueError('snapshot'),KeyboardInterrupt('snapshot'),SystemExit('snapshot')):
            with self.subTest(kind=type(failure).__name__):
                h=host(); calls=[]
                def choices(*,nonblocking=False):
                    calls.append(nonblocking)
                    if len(calls)==3:raise failure
                    return ['Stub','Auto','NEW']
                with patch.object(sp,'port_choices',side_effect=choices),patch.object(sp,'rc_port_choices',return_value=['Auto','DJI']):
                    with self.assertRaises(type(failure)) as caught:sp.refresh_port_options(h.registry,nonblocking=True)
                self.assertIs(caught.exception,failure)
                self.assertIn('NEW',h.settings['Port'].options)
                self.assertEqual(h.settings['Angle RX Port'].options,['ABSENT_RX'])

    def test_completion_uses_current_registry_without_replaying_old_values(self):
        h=host(); newer=host(); newer.settings['Angle RX Port'].value='NEW_SELECTION'
        with discovery_fixture() as d:
            h.rescan_serial_ports(); d.workers[0].target(); h.registry=newer.registry
            h.callbacks.pop(0)[1]()
        self.assertEqual(h.settings['Angle RX Port'].options,['ABSENT_RX'])
        self.assertIn('NEW_SELECTION',newer.settings['Angle RX Port'].options)
        self.assertEqual(newer.settings['Angle RX Port'].value,'NEW_SELECTION')

    def test_idempotent_options_return_no_changes_on_repeated_completion(self):
        h=host()
        with patch.object(sp,'port_snapshot',return_value=[]),patch.object(sp,'list_serial_ports',return_value=[]):
            first=sp.refresh_port_options(h.registry,nonblocking=True)
            second=sp.refresh_port_options(h.registry,nonblocking=True)
        self.assertTrue(first); self.assertEqual(second,[])


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SerialRescanNonblockingTests))
    blocked=[n for n in sys.modules if n.startswith(('PySide6','OpenGL','rm_client.backend.manager','rm_client.ui.polar_app','rm_client.auto_spin'))]
    assert not blocked,blocked
    print('Actual rescan AST plus pure discovery; all scans, timers, neutral retries and saves inert.')
    sys.exit(not result.wasSuccessful())
