"""Execute only the archive helper under PowerShell, never the release builder.

Set POLAR_TEST_PWSH to an official portable runtime, or use pwsh on PATH.
Linux execution does not qualify Windows PowerShell or Windows filesystem locks.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PWSH = os.environ.get('POLAR_TEST_PWSH') or shutil.which('pwsh')


@unittest.skipUnless(PWSH, 'PowerShell runtime required for archive publication')
class ReleaseArchivePublicationTests(unittest.TestCase):
    def invoke(self, source, output, *, lock_source=False, reject_replace=False, reject_cleanup=False):
        script = r'''
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($args[0], [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Builder syntax errors' }
$function = $ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Publish-ReleaseArchive'}, $true)
if ($null -eq $function) { throw 'Publication helper missing' }
$definition = $function.Extent.Text
if ($args[3] -eq 'reject-replace') {
    $call = '[System.IO.File]::Replace($candidate, $Destination, [NullString]::Value)'
    if (-not $definition.Contains($call)) { throw 'Replacement injection boundary missing' }
    $definition = $definition.Replace($call, "throw 'Injected replacement failure'")
}
if ($args[3] -eq 'reject-cleanup') {
    $WarningPreference = 'Stop'
    $delete = '[System.IO.File]::Delete($candidate)'
    if (-not $definition.Contains($delete)) { throw 'Cleanup injection boundary missing' }
    $definition = $definition.Replace($delete, "throw 'Injected cleanup failure'")
    $definition = $definition.Replace('[System.IO.Compression.ZipFile]::CreateFromDirectory(',
        'try { [System.IO.Compression.ZipFile]::CreateFromDirectory(').Replace(
        '::Optimal, $true)', '::Optimal, $true) } catch { $global:primaryFailure = $_.Exception; throw }')
}
Invoke-Expression $definition
$lock = $null
try {
    if ($args[3] -eq 'lock') {
        $lock = [System.IO.File]::Open((Join-Path $args[1] 'payload.txt'), 'Open', 'Read', 'None')
    }
    Write-Output 'PUBLICATION_HELPER_ENTERED'
    Publish-ReleaseArchive $args[1] $args[2]
} catch {
    if ($args[3] -eq 'reject-cleanup') {
        Write-Output ('PRIMARY_EXCEPTION_PRESERVED=' + [object]::ReferenceEquals($_.Exception, $global:primaryFailure))
    }
    throw
} finally { if ($null -ne $lock) { $lock.Dispose() } }
'''
        harness = output.parent / 'harness.ps1'
        harness.write_text(script, encoding='utf-8')
        environment = dict(os.environ, XDG_CACHE_HOME=str(output.parent / 'cache'),
                           XDG_CONFIG_HOME=str(output.parent / 'config'),
                           XDG_DATA_HOME=str(output.parent / 'data'))
        result = subprocess.run([PWSH, '-NoLogo', '-NoProfile', '-File', str(harness),
                               str(ROOT / 'tools/build_release.ps1'), str(source), str(output),
                               'reject-cleanup' if reject_cleanup else ('reject-replace' if reject_replace else ('lock' if lock_source else 'normal'))], capture_output=True,
                              text=True, timeout=30, env=environment)
        self.assertIn('PUBLICATION_HELPER_ENTERED', result.stdout, result.stderr)
        return result

    def test_builder_publishes_before_success_without_upfront_deletion(self):
        source = (ROOT / 'tools/build_release.ps1').read_text(encoding='utf-8-sig')
        tail = source[source.index('    $destination = Split-Path -Parent $outputPath'):]
        self.assertNotIn('Remove-Item -LiteralPath $outputPath', tail)
        self.assertLess(tail.index('Publish-ReleaseArchive $portable $outputPath'),
                        tail.index('$buildSucceeded = $true'))

    def test_success_creates_or_replaces_complete_zip(self):
        for existing in (False, True):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); source = root / 'candidate'; source.mkdir()
                (source / 'payload.txt').write_bytes(b'new payload')
                output = root / 'release.zip'
                if existing: output.write_bytes(b'previous candidate')
                result = self.invoke(source, output)
                self.assertEqual(result.returncode, 0, result.stderr)
                with zipfile.ZipFile(output) as archive:
                    self.assertEqual(archive.read('candidate/payload.txt'), b'new payload')
                self.assertEqual(list(root.glob('.polar-release-*.zip')), [])

    def test_creation_failure_preserves_previous_or_absent_output(self):
        for existing in (False, True):
            for partial in (False, True):
                with self.subTest(existing=existing, partial=partial), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp); source = root / 'candidate'; output = root / 'release.zip'
                    if partial:
                        source.mkdir(); (source / 'payload.txt').write_bytes(b'locked payload')
                    if existing: output.write_bytes(b'previous candidate')
                    result = self.invoke(source, output, lock_source=partial)
                    self.assertNotEqual(result.returncode, 0)
                    if existing: self.assertEqual(output.read_bytes(), b'previous candidate')
                    else: self.assertFalse(output.exists())
                    self.assertEqual(list(root.glob('.polar-release-*.zip')), [])

    def test_injected_replace_failure_preserves_previous_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / 'candidate'; source.mkdir()
            (source / 'payload.txt').write_bytes(b'new payload')
            output = root / 'release.zip'; output.write_bytes(b'previous candidate')
            result = self.invoke(source, output, reject_replace=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Injected replacement failure', result.stderr)
            self.assertEqual(output.read_bytes(), b'previous candidate')
            self.assertEqual(list(root.glob('.polar-release-*.zip')), [])

    def test_cleanup_warning_under_stop_preserves_primary_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); output = root / 'release.zip'
            output.write_bytes(b'previous candidate')
            result = self.invoke(root / 'missing-source', output, reject_cleanup=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('PRIMARY_EXCEPTION_PRESERVED=True', result.stdout)
            self.assertIn('Temporary release archive retained:', result.stdout)
            self.assertEqual(output.read_bytes(), b'previous candidate')
            self.assertEqual(len(list(root.glob('.polar-release-*.zip'))), 1)

    def test_publication_failure_does_not_remove_destination_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / 'candidate'; source.mkdir()
            (source / 'payload.txt').write_bytes(b'new payload')
            output = root / 'release.zip'; output.mkdir()
            (output / 'sentinel').write_bytes(b'keep')
            result = self.invoke(source, output)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((output / 'sentinel').read_bytes(), b'keep')
            self.assertEqual(list(root.glob('.polar-release-*.zip')), [])


if __name__ == '__main__':
    unittest.main()
