"""Production assembly must not execute an older private-pack DLL.

This runs the actual path validator and factory. Fake NativeApi owns no OS
window and never loads code, a game process, device or camera.
"""
from pathlib import Path
import hashlib
import json
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from rm_client.runtime_paths import RuntimePaths
from rm_client.ui.endfield.lifecycle import create_presentations
from rm_client.ui.endfield.menu.native import EndfieldNativeMenu, library_path


def renderer(pack,name,payload):
    root=pack/'native_renderer'/name;root.mkdir(parents=True)
    (root.parent/'CURRENT.json').write_text(json.dumps({'directory':name}),encoding='utf-8')
    (root/'polar_endfield.dll').write_bytes(payload)
    (root/'BUILD_MANIFEST.json').write_text(json.dumps({
        'reference_commit':'cdbd4f573c8fa3b9c2048fa3d1b089e69196537b',
        'binary_sha256':hashlib.sha256(payload).hexdigest()}),encoding='utf-8')
    return root/'polar_endfield.dll'


class RendererPriorityTests(unittest.TestCase):
    def setup_case(self,frozen):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);base=Path(temp.name)
        paths=RuntimePaths.discover(module_file=base/'source/rm_client/runtime_paths.py',
            executable=base/'portable/POLAR-RM.exe',frozen=frozen,environ={})
        shipped=paths.endfield_bundled_menu_pack
        current=renderer(shipped,'build_65994449a68ffa60',b'MZ shipped renderer')
        (shipped/'ENDFIELD_PACK_MANIFEST.json').write_text('{}',encoding='utf-8')
        private=paths.user_data_root/'endfield_pack'
        old=renderer(private,'build_83a5af809b9ccdb1',b'MZ old private renderer')
        (private/'boot').mkdir();(private/'boot/custom.bin').write_bytes(b'local boot/audio/resources')
        return paths,current,old

    def construct(self,paths):
        with patch('rm_client.ui.endfield.lifecycle.sys.platform','win32'), \
             patch('PySide6.QtWidgets.QApplication.platformName',return_value='windows'), \
             patch('rm_client.ui.endfield.lifecycle.EndfieldFeedback') as feedback, \
             patch('rm_client.ui.endfield.boot.EndfieldBootPresentation') as boot:
            presentations=create_presentations(paths)
            feedback.assert_called_once_with(paths.user_data_root/'endfield_pack')
            boot.assert_called_once_with(paths.user_data_root/'endfield_pack/boot')
        return presentations

    def test_old_private_pack_keeps_its_resources_but_factory_pins_current_dll(self):
        for frozen in (False,True):
            with self.subTest(frozen=frozen):
                paths,current,old=self.setup_case(frozen)
                private=paths.user_data_root/'endfield_pack'
                before={p.relative_to(private):p.read_bytes() for p in private.rglob('*') if p.is_file()}
                # Negative control: the omitted factory argument reproduces the
                # reported problem even with a valid newer shipped DLL present.
                self.assertEqual(library_path(EndfieldNativeMenu(private).renderer_pack),old)
                menu=self.construct(paths).menu
                self.assertEqual(menu.pack,private)
                self.assertEqual(menu.renderer_pack,paths.endfield_bundled_menu_pack)
                self.assertEqual(library_path(menu.renderer_pack),current)
                api=Mock();api.create.return_value=1
                with patch('rm_client.ui.endfield.menu.native.NativeApi',return_value=api) as native:
                    menu.prepare(0,1280,720,offscreen=True)
                native.assert_called_once_with(current)
                self.assertNotEqual(native.call_args.args[0],old)
                self.assertEqual(Path(api.create.call_args.args[1].decode()),private/'native_source_runtime')
                self.assertEqual(before,{p.relative_to(private):p.read_bytes() for p in private.rglob('*') if p.is_file()})

    def test_bad_shipped_hash_stays_diagnosable_never_falls_back_to_old_dll(self):
        paths,current,_old=self.setup_case(False)
        current.write_bytes(b'corrupt')
        menu=self.construct(paths).menu
        with patch('rm_client.ui.endfield.menu.native.NativeApi') as native:
            menu.prepare(0,1280,720,offscreen=True)
        native.assert_not_called()
        self.assertEqual(menu.handle,0)
        self.assertIn('hash differs',menu.error)

    def test_missing_bundled_renderer_never_silently_executes_private_code(self):
        for frozen in (False,True):
            with self.subTest(frozen=frozen),tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                paths=RuntimePaths.discover(module_file=root/'source/rm_client/runtime_paths.py',
                    executable=root/'portable/POLAR-RM.exe',frozen=frozen,environ={})
                private=paths.user_data_root/'endfield_pack'
                renderer(private,'build_83a5af809b9ccdb1',b'MZ old private renderer')
                menu=self.construct(paths).menu
                self.assertEqual(menu.pack,private)
                self.assertEqual(menu.renderer_pack,paths.endfield_bundled_menu_pack)
                with patch('rm_client.ui.endfield.menu.native.NativeApi') as native:
                    menu.prepare(0,1280,720,offscreen=True)
                native.assert_not_called()
                self.assertEqual(menu.handle,0)
                self.assertIn('BUILD_MANIFEST.json',menu.error)


if __name__=='__main__':unittest.main()
