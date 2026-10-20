"""Real child-bootstrap counterevidence; temporary scripts have no external effects."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.verify_all import classify_output


class VerificationThreadExceptionTests(unittest.TestCase):
    def execute(self, body):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'probe.py'
            script.write_text(textwrap.dedent(body), encoding='utf-8')
            result = subprocess.run(
                [sys.executable, '-u', str(ROOT / 'tools/verify_all.py'), '--_execute', str(script)],
                cwd=ROOT, capture_output=True, text=True, timeout=10,
            )
        output = result.stdout + '\n' + result.stderr
        return result, output, classify_output(result.returncode, output)

    def test_joined_uncaught_assertion_overrides_unittest_ok(self):
        result, output, evidence = self.execute('''
            import threading, unittest
            class Probe(unittest.TestCase):
                def test_worker(self):
                    def worker():
                        raise AssertionError('uncaught worker assertion')
                    thread = threading.Thread(target=worker)
                    thread.start()
                    thread.join()
                    self.assertFalse(thread.is_alive())
            unittest.main()
        ''')
        self.assertEqual(result.returncode, 0)  # Keep direct-script exit semantics.
        self.assertIn('OK', output)
        self.assertIn('AssertionError: uncaught worker assertion', output)
        self.assertEqual(evidence.status, 'FAIL')
        self.assertIn('[FAIL]', output)

    def test_unterminated_stderr_cannot_hide_failure_marker(self):
        result, output, evidence = self.execute('''
            import sys, threading
            sys.stderr.write('progress: ')
            sys.stderr.flush()
            def worker():
                raise RuntimeError('error after partial diagnostic')
            thread = threading.Thread(target=worker)
            thread.start(); thread.join()
            print('[PASS] main assertion')
        ''')
        self.assertEqual(result.returncode, 0)
        self.assertIn('RuntimeError: error after partial diagnostic', output)
        self.assertEqual(evidence.status, 'FAIL')
        self.assertRegex(output, r'(?m)^\[FAIL\]')

    def test_uncaught_after_target_returns_is_still_failure(self):
        result, output, evidence = self.execute('''
            import faulthandler, threading
            finished = threading.Event()
            original_cancel = faulthandler.cancel_dump_traceback_later
            def cancel():
                original_cancel()
                finished.set()  # Last bootstrap cleanup step, after runpy returns.
            faulthandler.cancel_dump_traceback_later = cancel
            def worker():
                if not finished.wait(3):
                    raise RuntimeError('bootstrap cleanup was not reached')
                raise ValueError('late worker counterevidence')
            threading.Thread(target=worker).start()
            print('[PASS] target returned')
        ''')
        self.assertEqual(result.returncode, 0)
        self.assertIn('ValueError: late worker counterevidence', output)
        self.assertNotIn('cleanup was not reached', output)
        self.assertEqual(evidence.status, 'FAIL')

    def test_healthy_and_caught_error_workers_remain_pass(self):
        result, output, evidence = self.execute('''
            import threading
            seen = []
            def worker():
                try:
                    raise ValueError('intentionally caught')
                except ValueError as error:
                    seen.append(str(error))
            thread = threading.Thread(target=worker)
            thread.start(); thread.join()
            assert seen == ['intentionally caught']
            print('[PASS] healthy worker completed with expected caught error')
        ''')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(evidence.status, 'PASS')
        self.assertNotIn('[FAIL]', output)

    def test_thread_system_exit_retains_default_ignored_semantics(self):
        result, output, evidence = self.execute('''
            import threading
            def worker():
                raise SystemExit(7)
            thread = threading.Thread(target=worker)
            thread.start(); thread.join()
            print('[PASS] thread SystemExit remains local')
        ''')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(evidence.status, 'PASS')
        self.assertNotIn('[FAIL]', output)

    def test_scoped_custom_hook_can_capture_expected_exception(self):
        result, output, evidence = self.execute('''
            import threading
            seen = []
            original = threading.excepthook
            def worker():
                raise ValueError('explicitly asserted by hook')
            try:
                threading.excepthook = lambda args: seen.append((args.exc_type, str(args.exc_value)))
                thread = threading.Thread(target=worker)
                thread.start(); thread.join()
            finally:
                threading.excepthook = original
            assert seen == [(ValueError, 'explicitly asserted by hook')]
            print('[PASS] custom hook asserted expected exception')
        ''')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(evidence.status, 'PASS')
        self.assertNotIn('[FAIL]', output)

    def test_main_thread_nonzero_exit_preserved(self):
        result, output, evidence = self.execute('''
            print('[PASS] earlier assertion')
            raise SystemExit(9)
        ''')
        self.assertEqual(result.returncode, 9)
        self.assertEqual(evidence.status, 'FAIL')


if __name__ == '__main__':
    unittest.main()
