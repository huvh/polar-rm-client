"""Actual queued Qt callbacks through the verifier's child bootstrap."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.verify_all import classify_output


class VerificationQtExceptionTests(unittest.TestCase):
    def execute(self, action, *, setup='', expected='True'):
        source = '''
import sys, unittest
from PySide6.QtCore import QObject, Signal, Slot, Qt
from PySide6.QtWidgets import QApplication
app = QApplication([])
seen = []
SETUP
class Receiver(QObject):
    trigger = Signal()
    @Slot()
    def receive(self):
        seen.append('called')
ACTION
class Probe(unittest.TestCase):
    def test_queued_callback(self):
        receiver = Receiver()
        receiver.trigger.connect(receiver.receive, Qt.ConnectionType.QueuedConnection)
        receiver.trigger.emit()
        app.processEvents()
        self.assertEqual(seen[0], 'called')
        self.assertTrue(EXPECTED)
unittest.main()
'''.replace('SETUP', setup).replace('ACTION', textwrap.indent(textwrap.dedent(action), '        ')).replace('EXPECTED', expected)
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'qt_probe.py'
            script.write_text(source, encoding='utf-8')
            env = dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONDONTWRITEBYTECODE='1')
            result = subprocess.run([sys.executable, '-u', str(ROOT / 'tools/verify_all.py'),
                                     '--_execute', str(script)], cwd=ROOT, env=env,
                                    capture_output=True, text=True, timeout=15)
        output = result.stdout + '\n' + result.stderr
        return result, output, classify_output(result.returncode, output)

    def test_uncaught_queued_slot_overrides_unittest_success(self):
        result, output, evidence = self.execute("raise AssertionError('queued slot counterevidence')")
        self.assertEqual(result.returncode, 0)
        self.assertIn('OK', output)
        self.assertIn('AssertionError: queued slot counterevidence', output)
        self.assertEqual(evidence.status, 'FAIL')
        self.assertRegex(output, r'(?m)^\[FAIL\]')

    def test_unterminated_stderr_cannot_hide_marker(self):
        result, output, evidence = self.execute("raise ValueError('partial stderr callback failure')",
            setup="sys.stderr.write('progress: '); sys.stderr.flush()")
        self.assertEqual(result.returncode, 0)
        self.assertIn('ValueError: partial stderr callback failure', output)
        self.assertEqual(evidence.status, 'FAIL')
        self.assertRegex(output, r'(?m)^\[FAIL\]')

    def test_healthy_queued_slot_passes(self):
        result, output, evidence = self.execute("seen.append('healthy')", expected="seen == ['called', 'healthy']")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(evidence.status, 'PASS')
        self.assertNotIn('[FAIL]', output)

    def test_caught_callback_exception_passes(self):
        result, output, evidence = self.execute('''
            try:
                raise ValueError('caught intentionally')
            except ValueError as error:
                seen.append(str(error))
        ''', expected="seen == ['called', 'caught intentionally']")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(evidence.status, 'PASS')
        self.assertNotIn('[FAIL]', output)

    def test_custom_handler_explicitly_asserts_expected_exception(self):
        setup = '''original = sys.excepthook
errors = []
def capture(kind, value, traceback):
    errors.append((kind, str(value)))
    sys.excepthook = original
sys.excepthook = capture'''
        result, output, evidence = self.execute("raise ValueError('expected by handler')", setup=setup,
            expected="errors == [(ValueError, 'expected by handler')] and sys.excepthook is original")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(evidence.status, 'PASS')
        self.assertNotIn('[FAIL]', output)

    def test_qt_system_exit_retains_child_exit_code(self):
        result, output, evidence = self.execute('raise SystemExit(7)')
        self.assertEqual(result.returncode, 7)
        self.assertNotIn('[FAIL]', output)
        self.assertEqual(evidence.status, 'FAIL')


if __name__ == '__main__':
    unittest.main()
