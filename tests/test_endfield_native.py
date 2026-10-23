"""Native owner/path contracts without loading a DLL or touching hardware."""
from pathlib import Path
import hashlib
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rm_client.ui.endfield_native import EndfieldNativeMenu, library_path


class NativeOwnerTests(unittest.TestCase):
    def test_library_pin_hash_and_version_path(self):
        with tempfile.TemporaryDirectory() as directory:
            pack = Path(directory)
            root = pack / "native_renderer"
            version = root / ("build_" + "a"*16)
            version.mkdir(parents=True)
            library = version / "polar_endfield.dll"
            library.write_bytes(b"not executed")
            manifest = {"reference_commit": "cdbd4f573c8fa3b9c2048fa3d1b089e69196537b",
                        "binary_sha256": hashlib.sha256(library.read_bytes()).hexdigest()}
            (version / "BUILD_MANIFEST.json").write_text(json.dumps(manifest))
            current = root / "CURRENT.json"
            current.write_text(json.dumps({"directory": version.name}))
            self.assertEqual(library_path(pack), library)
            library.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "hash"):
                library_path(pack)
            for invalid in ("../outside", "build_../outside", "build_build", 12):
                current.write_text(json.dumps({"directory": invalid}))
                with self.assertRaises(ValueError):
                    library_path(pack)

    def make_owner(self):
        menu = EndfieldNativeMenu(Path("unused"))
        api = Mock(create=Mock(return_value=17), status=Mock(return_value=1))
        with patch("rm_client.ui.endfield_native.library_path", return_value=Path("unused.dll")), \
             patch("rm_client.ui.endfield_native.NativeApi", return_value=api):
            menu.request(True)
            menu.prepare(42, 1280, 720)
            menu.prepare(42, 1280, 720)
        api.create.assert_called_once()
        api.visible.assert_called_once_with(17, True)
        return menu, api

    def test_latest_context_cached_but_modal_pause_always_forwarded(self):
        menu, api = self.make_owner()
        for _ in range(100):
            menu.tick(width=1280, height=720, chinese=True, mode="RMUL3v3", paused=True)
        api.context.assert_called_once()
        api.resize.assert_called_once_with(17, 1280, 720)
        api.action.assert_not_called()
        self.assertEqual(api.pause.call_count, 100)

    def test_shipped_renderer_can_use_private_pinned_resources_without_loading_old_dll(self):
        menu = EndfieldNativeMenu(Path("private-scene"), renderer_pack=Path("shipped-code"))
        api = Mock(create=Mock(return_value=17), status=Mock(return_value=1))
        with patch("rm_client.ui.endfield_native.library_path", return_value=Path("fixed.dll")) as locate, \
             patch("rm_client.ui.endfield_native.NativeApi", return_value=api) as load:
            menu.prepare(42, 1280, 720)
        locate.assert_called_once_with(Path("shipped-code"))
        load.assert_called_once_with(Path("fixed.dll"))
        self.assertEqual(api.create.call_args.args[1],
                         os.fsencode(Path("private-scene/native_source_runtime")))

    def test_cleanup_retains_library_until_worker_ack(self):
        menu, api = self.make_owner()
        menu.close()
        self.assertFalse(menu.requested)
        api.destroy.assert_called_once_with(17)
        api.status.side_effect = [1, 2]
        menu.wait_closed()
        api.release.assert_called_once_with(17)
        self.assertEqual(menu.handle, 0)

    def test_native_reveal_waits_for_accepted_backdrop_and_real_qt_swap(self):
        menu, api = self.make_owner()
        api.visible.reset_mock()
        menu.request(True, wait_for_backdrop=True)
        self.assertEqual(menu.phase, 3)
        menu.backdrop_presented()  # Old/failed frame cannot reveal the child.
        api.visible.assert_called_once_with(17, False)
        menu.backdrop_frame_ready(False)
        menu.backdrop_presented()
        self.assertEqual(api.visible.call_count, 1)
        menu.backdrop_frame_ready(True)
        self.assertEqual(api.visible.call_count, 1)
        menu.backdrop_presented()
        api.visible.assert_called_with(17, True)
        menu.backdrop_presented()
        self.assertEqual(api.visible.call_count, 2)

    def test_close_or_reopen_discards_stale_backdrop_ack(self):
        menu, api = self.make_owner()
        menu.request(True, wait_for_backdrop=True)
        menu.backdrop_frame_ready(True)
        menu.request(False)
        menu.backdrop_presented()
        api.visible.assert_called_with(17, False)
        menu.request(True, wait_for_backdrop=True)
        menu.backdrop_presented()
        api.visible.assert_called_with(17, False)
        menu.backdrop_frame_ready(True)
        menu.close()
        calls = api.visible.call_count
        menu.backdrop_presented()
        self.assertEqual(api.visible.call_count, calls)

    def test_missing_abi_is_diagnostic_not_repeated_start(self):
        menu = EndfieldNativeMenu(Path("unused"))
        with patch("rm_client.ui.endfield_native.library_path", return_value=Path("old.dll")), \
             patch("rm_client.ui.endfield_native.NativeApi", side_effect=AttributeError("missing ABI")) as factory:
            menu.prepare(42, 1280, 720)
            menu.prepare(42, 1280, 720)
        self.assertIn("missing ABI", menu.error)
        self.assertFalse(menu.ready)
        factory.assert_called_once()


if __name__ == "__main__":
    unittest.main()
