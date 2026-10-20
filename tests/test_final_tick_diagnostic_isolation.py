"""Final telemetry warning failure cannot change the normal tick return contract.

Actual on_tick/publication AST and pure timing owner; every runtime collaborator
is inert. Earlier runtime work is already complete, not restored by this guard.
"""
import ast
import io
import logging
from pathlib import Path
import sys
from types import MethodType, SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import rm_client
from rm_client.ui.polar.tick_controller import TickDiagnostics
REPO=Path(rm_client.__file__).resolve().parent.parent
WINDOW_SOURCE=REPO/'rm_client/ui/polar_app.py'
PRIOR=['_poll_backend_lifecycle','_begin_ui_frame','_advance_input_and_scroll',
       '_advance_panel_presentation','_advance_economy_transaction','_advance_hud_presentation',
       '_advance_runtime_tick','_request_ui_frame']


def fixture(*, primary=None, logger=None, entry='on_tick', now=10.):
    cls=next(n for n in ast.parse(WINDOW_SOURCE.read_text()).body if isinstance(n,ast.ClassDef) and n.name=='PolarRMWindow')
    methods=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in {'on_tick','_publish_tick_performance'}]
    clock=Mock(side_effect=[now,now+.002] if entry=='on_tick' else [now+.002])
    logger=logger if logger is not None else Mock(spec=logging.Logger)
    scope=dict(time=NS(perf_counter=clock),_LOG=logger)
    exec(compile(ast.fix_missing_locations(ast.Module(body=methods,type_ignores=[])),str(WINDOW_SOURCE),'exec'),scope)
    owner=TickDiagnostics(count=3,last_error='kept error',last_logged_at={'work':9.},
        last_ms=3.,max_ms=17.,gap_ms=12.,gap_max_ms=30.,
        stages={'work':{'count':2,'total_ms':4.,'max_ms':3.}},reported_at=4.)
    host=NS(_tick_diagnostics=owner,state=NS(backend_stats={'other':object()}),frame_dt=.016,
        _gpu_prewarm_last_ms=3.,_gpu_prewarm_max_ms=7.,trace=[],records=[],warnings=[],clock=clock,
        logger=logger,primary=primary,entry=entry,now=now)
    finish=owner.finish_tick
    def finish_tick(*args): host.trace.append('finish'); return finish(*args)
    owner.finish_tick=finish_tick
    def emit(name,**metrics):
        host.trace.append('emit')
        host.records.append((name,metrics))
        if host.primary is not None: raise host.primary
    host.backend=NS(field_log=NS(emit=emit))
    for name in PRIOR:
        def call(*args,_name=name): host.trace.append(_name); return True if _name==PRIOR[0] else None
        setattr(host,name,call)
    host._publish_tick_performance=MethodType(scope['_publish_tick_performance'],host)
    host.on_tick=MethodType(scope['on_tick'],host)
    host.invoke=lambda: host.on_tick() if entry=='on_tick' else host._publish_tick_performance(host.now)
    return host


def closed_logger():
    stream=io.StringIO(); stream.close()
    logger=logging.Logger('final-tick-proof',logging.WARNING)
    logger.addHandler(logging.StreamHandler(stream))
    return logger,stream


class FinalTickDiagnosticTests(unittest.TestCase):
    def no_escape(self,host):
        error=result=None
        try: result=host.invoke()
        except Exception as caught: error=caught
        self.assertIsNone(error,'ordinary final diagnostic must preserve normal callback return')
        self.assertIsNone(result)

    def assert_published(self,host):
        metrics=host.state.backend_stats['ui_tick_performance']
        self.assertAlmostEqual(metrics['tick_ms'],2.)
        self.assertEqual({k:v for k,v in metrics.items() if k!='tick_ms'},
            dict(tick_max_ms=17.,wakeup_gap_ms=12.,wakeup_gap_max_ms=30.,
                 stages={'work':{'count':2,'total_ms':4.,'max_ms':3.}},
                 gpu_prewarm_last_ms=3.,gpu_prewarm_max_ms=7.))
        self.assertEqual(host.records,[('ui_tick_timing',metrics)])
        owner=host._tick_diagnostics
        self.assertEqual((owner.reported_at,owner.stages,owner.max_ms,owner.gap_max_ms),(host.now,{},0.,0.))
        self.assertEqual((owner.count,owner.last_error,owner.last_logged_at),(3,'kept error',{'work':9.}))
        self.assertEqual(host.clock.call_count,2 if host.entry=='on_tick' else 1)
        expected=PRIOR if host.entry=='on_tick' else []
        self.assertEqual(host.trace[:len(expected)+2],expected+['finish','emit'])
        return metrics

    def test_ordinary_warning_failure_preserves_return_for_both_actual_entrypoints(self):
        for entry in ['direct','on_tick']:
            for diagnostic in [OSError('log failed'),ValueError('closed sink')]:
                with self.subTest(entry=entry,diagnostic=type(diagnostic).__name__):
                    host=fixture(entry=entry,primary=RuntimeError('field log failed'),logger=Mock(warning=Mock(side_effect=diagnostic)))
                    self.no_escape(host)
                    self.assert_published(host)
                    host.logger.warning.assert_called_once_with('UI timing diagnostic could not be written',exc_info=True)

    def test_standard_closed_stderr_restores_return_without_replaying_prior_callbacks(self):
        for entry in ['direct','on_tick']:
            with self.subTest(entry=entry):
                logger,stream=closed_logger()
                host=fixture(entry=entry,primary=OSError('field log failed'),logger=logger)
                with patch.object(sys,'stderr',stream),patch.object(logging,'raiseExceptions',True):
                    self.no_escape(host)
                self.assert_published(host)
                for name in PRIOR: self.assertEqual(host.trace.count(name),int(entry=='on_tick'))

    def test_warning_lookup_failure_is_inside_guard(self):
        class Logger:
            @property
            def warning(self): raise AttributeError('warning lookup failed')
        host=fixture(primary=ValueError('field log failed'),logger=Logger())
        self.no_escape(host)
        self.assert_published(host)

    def test_field_log_lookup_failure_uses_existing_fallback_in_original_context(self):
        primary=RuntimeError('field log lookup failed')
        seen=[]
        class Backend:
            @property
            def field_log(self): raise primary
        def warning(*a,**kw): seen.append((sys.exc_info()[1],a,kw)); raise OSError('diagnostic failed')
        host=fixture(logger=NS(warning=warning)); host.backend=Backend()
        self.no_escape(host)
        self.assertEqual(seen,[(primary,('UI timing diagnostic could not be written',),{'exc_info':True})])
        self.assertIn('ui_tick_performance',host.state.backend_stats)
        self.assertEqual(host._tick_diagnostics.reported_at,10.)
        self.assertEqual(host.trace,PRIOR+['finish'])

    def test_healthy_field_sink_never_uses_warning_even_when_warning_is_broken(self):
        for entry in ['direct','on_tick']:
            with self.subTest(entry=entry):
                host=fixture(entry=entry,logger=Mock(warning=Mock(side_effect=OSError('must not call'))))
                self.no_escape(host)
                self.assert_published(host)
                host.logger.warning.assert_not_called()

    def test_healthy_warning_retains_original_context_exact_message_and_order(self):
        primary=ValueError('field failure')
        seen=[]
        host=fixture(primary=primary)
        def warning(*a,**kw):
            host.trace.append('warning'); seen.append((sys.exc_info()[1],a,kw))
            self.assertIn('ui_tick_performance',host.state.backend_stats)
        host.logger.warning.side_effect=warning
        self.no_escape(host)
        self.assert_published(host)
        self.assertEqual(seen,[(primary,('UI timing diagnostic could not be written',),{'exc_info':True})])
        self.assertEqual(host.trace,PRIOR+['finish','emit','warning'])

    def test_report_window_and_lifetime_state_are_consumed_before_failed_diagnostics(self):
        host=fixture(primary=OSError('field failed'))
        stages=host._tick_diagnostics.stages
        def warning(*a,**kw):
            self.assertEqual((host._tick_diagnostics.reported_at,stages),(10.,{}))
            self.assertEqual(host._tick_diagnostics.count,3)
            raise OSError('warning failed')
        host.logger.warning.side_effect=warning
        self.no_escape(host)
        metrics=self.assert_published(host)
        self.assertIs(stages,host._tick_diagnostics.stages)
        self.assertIsNot(metrics['stages'],stages)
        stages['later']={'count':1.}
        self.assertNotIn('later',metrics['stages'])

    def test_failed_diagnostic_does_not_reset_five_second_rate_or_replay_record(self):
        host=fixture(entry='direct',primary=ValueError('field failed'),logger=Mock(warning=Mock(side_effect=OSError('warning failed'))))
        self.no_escape(host)
        old=self.assert_published(host)
        host.clock.side_effect=None
        host.clock.return_value=14.9991
        host._publish_tick_performance(14.999)
        self.assertEqual(len(host.records),1)
        self.assertIs(host.state.backend_stats['ui_tick_performance'],old)
        self.assertEqual(host._tick_diagnostics.reported_at,10.)
        host.primary=None
        host.clock.return_value=15.001
        host._publish_tick_performance(15.)
        self.assertEqual(len(host.records),2)
        self.assertEqual(host._tick_diagnostics.reported_at,15.)
        self.assertIsNot(host.state.backend_stats['ui_tick_performance'],old)
        self.assertEqual(host.logger.warning.call_count,1)

    def test_no_due_report_keeps_previous_metric_object_and_skips_both_sinks(self):
        for entry in ['direct','on_tick']:
            with self.subTest(entry=entry):
                host=fixture(entry=entry,primary=OSError('must not call'))
                host._tick_diagnostics.reported_at=9.
                old={'kept':True}; host.state.backend_stats['ui_tick_performance']=old
                self.no_escape(host)
                self.assertIs(host.state.backend_stats['ui_tick_performance'],old)
                self.assertEqual(host.records,[])
                self.assertEqual(host._tick_diagnostics.reported_at,9.)
                self.assertEqual(host._tick_diagnostics.stages['work']['count'],2)
                host.logger.warning.assert_not_called()

    def test_lifecycle_gate_skips_reporting_and_every_later_actual_callback(self):
        host=fixture(primary=OSError('must not call'))
        def closed(): host.trace.append(PRIOR[0]); return False
        host._poll_backend_lifecycle=closed
        self.no_escape(host)
        self.assertEqual(host.trace,[PRIOR[0]])
        self.assertEqual(host.clock.call_count,1)
        self.assertEqual(host._tick_diagnostics.reported_at,4.)
        self.assertNotIn('ui_tick_performance',host.state.backend_stats)
        host.logger.warning.assert_not_called()

    def test_field_process_control_preserves_identity_metrics_window_and_no_warning(self):
        for entry in ['direct','on_tick']:
            for failure in [KeyboardInterrupt('field stop'),SystemExit('field stop')]:
                with self.subTest(entry=entry,kind=type(failure).__name__):
                    host=fixture(entry=entry,primary=failure)
                    with self.assertRaises(type(failure)) as caught: host.invoke()
                    self.assertIs(caught.exception,failure)
                    self.assert_published(host)
                    host.logger.warning.assert_not_called()

    def test_warning_process_control_preserves_identity_metrics_and_prior_prefix(self):
        for entry in ['direct','on_tick']:
            for failure in [KeyboardInterrupt('warning stop'),SystemExit('warning stop')]:
                with self.subTest(entry=entry,kind=type(failure).__name__):
                    host=fixture(entry=entry,primary=OSError('field failed'),logger=Mock(warning=Mock(side_effect=failure)))
                    with self.assertRaises(type(failure)) as caught: host.invoke()
                    self.assertIs(caught.exception,failure)
                    self.assert_published(host)
                    self.assertEqual(host.logger.warning.call_count,1)

    def test_prior_callback_failure_still_prevents_final_publication(self):
        for failure in [RuntimeError('prior callback failed'),KeyboardInterrupt('prior stop')]:
            with self.subTest(kind=type(failure).__name__):
                host=fixture()
                def failed(now): host.trace.append('_request_ui_frame'); raise failure
                host._request_ui_frame=failed
                with self.assertRaises(type(failure)) as caught: host.invoke()
                self.assertIs(caught.exception,failure)
                self.assertEqual(host.trace,PRIOR)
                self.assertEqual(host._tick_diagnostics.reported_at,4.)
                self.assertEqual(host.records,[])
                host.logger.warning.assert_not_called()

    def test_finish_clock_and_report_formatting_failures_remain_outside_guard(self):
        for location in ['clock','finish','metrics']:
            with self.subTest(location=location):
                failure=ValueError(location+' failed')
                host=fixture(entry='direct')
                if location=='clock': host.clock.side_effect=failure
                elif location=='finish': host._tick_diagnostics.finish_tick=Mock(side_effect=failure)
                else: host._tick_diagnostics.finish_tick=Mock(return_value=NS(metrics=Mock(side_effect=failure)))
                with self.assertRaises(ValueError) as caught: host.invoke()
                self.assertIs(caught.exception,failure)
                self.assertNotIn('ui_tick_performance',host.state.backend_stats)
                self.assertEqual(host.records,[])
                host.logger.warning.assert_not_called()

    def test_metric_mapping_failure_keeps_existing_consumed_window_prefix(self):
        failure=TypeError('mapping rejected')
        class Mapping(dict):
            def __setitem__(self,key,value): raise failure
        host=fixture(entry='direct'); host.state.backend_stats=Mapping()
        with self.assertRaises(TypeError) as caught: host.invoke()
        self.assertIs(caught.exception,failure)
        self.assertEqual(host._tick_diagnostics.reported_at,10.)
        self.assertEqual(host._tick_diagnostics.stages,{})
        self.assertEqual(host.records,[])
        host.logger.warning.assert_not_called()

    def test_reported_metric_keeps_pre_sink_mutation_semantics(self):
        host=fixture(entry='direct',logger=Mock(warning=Mock(side_effect=OSError('warning failed'))))
        def emit(name,**metrics):
            metrics['stages']['work']['count']=99
            raise ValueError('sink mutated its nested input before failing')
        host.backend.field_log.emit=emit
        self.no_escape(host)
        self.assertEqual(host.state.backend_stats['ui_tick_performance']['stages']['work']['count'],99)
        self.assertEqual(host._tick_diagnostics.stages,{})
        self.assertEqual(host._tick_diagnostics.reported_at,10.)

if __name__=='__main__': unittest.main(verbosity=2)
