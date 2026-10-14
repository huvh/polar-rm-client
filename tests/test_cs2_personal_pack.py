"""Offline assets, hot-path I/O, feedback semantics and import safety checks."""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch
import zlib

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("POLAR_DISABLE_MEDIA_PRELOAD", "1")
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication
from rm_client.kill_fx import KillFxRenderer, TriggerContext
from rm_client.combat_events import CombatEvent
from rm_client.model import build_default_registry
from rm_client.ui.cs2_assets import Cs2Assets
from rm_client.ui.cs2_feedback import BuyFeedback, append_buy_feedback, card_targets, kill_brightness, kill_spotlight
from rm_client.ui.cs2_kill_feedback import Cs2KillFeedback
from rm_client.ui.clickgui_gpu import ClickGuiDrawList
from rm_client.ui.top_match_bar import TopMatchBarOptions, TopMatchBarRenderer
from tools.import_cs2_ui_pack import extract_member, validate_destinations, vpk_index
from test_cs2_match_strip_style import fixture_frame, render, ensure_qt_fonts


class PersonalPackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        ensure_qt_fonts()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def pack(self):
        assets = {}
        for key in ("dots", "kill_1", "kill_default", "kill_mask", "kill_flag", "person", "money"):
            image = QImage(32, 64, QImage.Format_ARGB32_Premultiplied)
            image.fill(QColor(255, 255, 255, 128))
            dest = self.root / (key + ".png")
            self.assertTrue(image.save(str(dest)))
            assets[key] = {"file": dest.name, "sha256": hashlib.sha256(dest.read_bytes()).hexdigest()}
        manifest = {"schema": 1, "scope": "local-personal-use", "assets": assets}
        (self.root / "manifest.json").write_text(json.dumps(manifest))
        return manifest

    def test_absent_pack_is_original_fallback(self):
        pack = Cs2Assets(self.root)
        self.assertFalse(pack.available)
        self.assertFalse(pack.play("kill", .5))
        self.assertTrue(pack.image("missing").isNull())

    def test_hash_mismatch_is_all_or_nothing(self):
        self.pack()
        (self.root / "kill_1.png").write_bytes(b"bad")
        pack = Cs2Assets(self.root)
        self.assertFalse(pack.available)
        self.assertFalse(pack.paths)
        self.assertIn("hash mismatch", pack.error)

    def test_traversal_absolute_and_unknown_ids_rejected(self):
        manifest = self.pack()
        for key, filename in (("dots", "../outside.png"), ("dots", str(self.root/"dots.png")), ("arbitrary", "dots.png")):
            with self.subTest(key=key, filename=filename):
                changed = json.loads(json.dumps(manifest))
                changed["assets"][key] = {"file": filename, "sha256": "0"*64}
                (self.root / "manifest.json").write_text(json.dumps(changed))
                self.assertFalse(Cs2Assets(self.root).available)

    def test_shaped_tint_and_warm_paint_have_no_file_io(self):
        self.pack()
        pack = Cs2Assets(self.root)
        self.assertTrue(pack.available)
        renderer = TopMatchBarRenderer(pack)
        frame = fixture_frame()
        before = asdict(frame)
        image, _ = render(frame, renderer=renderer)
        with patch.object(Path, "read_bytes", side_effect=AssertionError("paint performed file I/O")):
            repeat, _ = render(frame, renderer=renderer)
            self.assertEqual(image, repeat)
            a = pack.tinted("person", QColor("#EAD18A"))
            self.assertEqual(a.cacheKey(), pack.tinted("person", QColor("#EAD18A")).cacheKey())
        self.assertEqual(asdict(frame), before)

    def test_audio_uses_existing_percentage_volume_and_missing_does_not_spawn(self):
        pack = Cs2Assets()
        pack.paths["kill"] = self.root / "kill.wav"
        pack._audio = Mock()
        pack._audio.play.return_value = True
        self.assertTrue(pack.play("kill", .55))
        self.assertEqual(pack._audio.play.call_args.args[0], "kill.wav")
        self.assertAlmostEqual(pack._audio.play.call_args.args[1], 33.0)
        self.assertFalse(pack.play("missing", .55))

    def test_import_destination_guard(self):
        game = self.root / "game"
        for work, output, cli in ((game/"work", self.root/"out", self.root/"cli.exe"),
                                  (self.root/"work", game/"out", self.root/"cli.exe"),
                                  (self.root/"work", self.root/"out", game/"cli.exe")):
            with self.assertRaises(ValueError):
                validate_destinations(game, work, output, cli)
        validate_destinations(game, self.root/"work", self.root/"out", self.root/"cli.exe")

    def test_vpk_embedded_copy_crc_and_preload(self):
        payload = b"copied texture"
        head = b"pre"
        crc = zlib.crc32(head+payload) & 0xffffffff
        entry = struct.pack("<IHHIIH", crc, len(head), 32767, 0, len(payload), 65535) + head
        tree = b"vtex_c\0panorama/images/hud\0icon\0" + entry + b"\0\0\0"
        path = self.root / "pak01_dir.vpk"
        path.write_bytes(struct.pack("<III", 0x55AA1234, 2, len(tree)) + bytes(16) + tree + payload)
        items = vpk_index(path)
        d = items["panorama/images/hud/icon.vtex_c"]
        self.assertEqual(extract_member(path, d), head+payload)
        with self.assertRaises(ValueError):
            extract_member(path, (0, *d[1:]))

    def test_registry_additions_do_not_change_defaults_or_protocol(self):
        registry = build_default_registry()
        self.assertIn("CS2 Native", registry.get("EliminationFX").get_setting("Preset").options)
        self.assertEqual(registry.get("EliminationFX").get_setting("Preset").value, "Default Scrolling")
        self.assertTrue(registry.get("TopMatchBar").get_setting("Local CS2 Assets").value)
        self.assertTrue(registry.get("EconomyPanel").get_setting("CS2 Feedback").value)
        self.assertFalse(registry.get("EconomyPanel").get_setting("Mock Requests").value)


class FeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def context(self, combo=1, now=10):
        return TriggerContext("NORMAL", combo, 101, "robot", 1, 0, (), now)

    def test_source_kill_keyframes(self):
        self.assertEqual(kill_brightness(0), 6)
        self.assertEqual(kill_brightness(.21), 6)
        self.assertEqual(kill_brightness(.7), 1)
        self.assertEqual(kill_spotlight(0), 0)
        self.assertAlmostEqual(kill_spotlight(.007), .2)
        self.assertEqual(kill_spotlight(.7), 0)
        self.assertEqual(card_targets(5), ((-7,8,-24),(-3,6,-12),(0,4,0),(3,2,12),(7,0,24)))

    def test_reflow_is_continuous_and_fps_independent(self):
        fan = Cs2KillFeedback(Cs2Assets())
        fan.trigger(self.context(), 10)
        self.assertEqual(fan.poses(10), [(0,42,0)])
        self.assertTrue(all(abs(value) < 1e-8 for value in fan.poses(10.2)[0]))
        fan.trigger(self.context(2, 10.25), 10.25)
        before = fan.poses(10.3)
        fan.trigger(self.context(3, 10.3), 10.3)
        self.assertEqual(fan.poses(10.3)[:2], before)
        final = fan.poses(10.5)
        for i in range(20):
            fan.poses(10.3 + i/100)
        self.assertEqual(final, fan.poses(10.5))

    def test_missing_previous_kills_not_invented_and_bounded_reset(self):
        fan = Cs2KillFeedback(Cs2Assets())
        fan.trigger(self.context(4), 10)
        self.assertEqual(len(fan.cards), 1)
        for i in range(50):
            fan.trigger(self.context(i+5, 10+i), 10+i)
        self.assertEqual(len(fan.cards), 5)
        fan.trigger(self.context(1, 60), 60)
        self.assertEqual(len(fan.cards), 1)
        fan.clear()
        self.assertFalse(fan.cards)

    def test_original_fallback_has_pixels_and_restores_painter(self):
        fan = Cs2KillFeedback(Cs2Assets())
        fan.trigger(self.context(), 10)
        image = QImage(200, 300, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        p = QPainter(image)
        p.setOpacity(.8)
        transform = p.transform()
        fan.draw(p, QPointF(100, 150), 10.2, 1)
        self.assertEqual(p.transform(), transform)
        self.assertEqual(p.opacity(), .8)
        p.end()
        self.assertTrue(any(image.pixelColor(x,y).alpha() for x in range(80,120) for y in range(75,140)))

    def test_existing_fx_dispatch_reset_and_preset_filter(self):
        with patch("rm_client.kill_fx.local_cs2_assets", return_value=Cs2Assets()):
            renderer = KillFxRenderer(Path("missing-original-assets"))
        event = CombatEvent("elimination", "referee", True, 10, victim_id=101)
        renderer.trigger(event, combo_window=5, sound_enabled=False, volume=50,
                         preset="CS2 Native", visibility="Preset", now_override=10)
        self.assertEqual(len(renderer.cs2.cards), 1)
        self.assertEqual(KillFxRenderer.elements_for_preset("CS2 Native", "Icons Only"), ("cs2",))
        renderer.trigger(CombatEvent("death", "referee", True, 11), combo_window=5,
                         sound_enabled=False, volume=50, preset="CS2 Native", visibility="Preset", now_override=11)
        self.assertFalse(renderer.cs2.cards)
        renderer.clear()

    def test_purchase_only_terminal_success_and_rejection_no_timeout_claim(self):
        feedback = BuyFeedback()
        transaction = NS(sequence=1, offer=NS(key="ammo"), status="pending")
        self.assertIsNone(feedback.observe(transaction, 10))
        self.assertEqual(feedback.intensity("ammo", 10), 0)
        transaction.status = "succeeded"
        self.assertEqual(feedback.observe(transaction, 11), "purchase")
        self.assertEqual(feedback.intensity("ammo", 11), 1)
        self.assertAlmostEqual(feedback.intensity("ammo", 11.25), .5, places=4)
        self.assertEqual(feedback.intensity("ammo", 11.5), 0)
        self.assertEqual(feedback.intensity("wrong", 11), 0)
        self.assertIsNone(feedback.observe(transaction, 12))
        transaction.sequence = 2; transaction.status = "timed_out"
        self.assertIsNone(feedback.observe(transaction, 13))
        self.assertEqual(feedback.intensity("ammo", 13), 0)
        transaction.sequence = 3; transaction.status = "rejected"
        self.assertEqual(feedback.observe(transaction, 14), "cant_buy")

    def test_buy_commands_respect_clip_and_do_not_touch_glass(self):
        registry = build_default_registry()
        assets = Cs2Assets()
        image = QImage(2,2,QImage.Format_ARGB32_Premultiplied); image.fill(Qt.white)
        assets.images["buy_icon"] = image; assets.paths["buy_icon"] = Path("C:/private/buy_icon.png")
        owner = NS(registry=registry, kill_fx=NS(cs2=NS(assets=assets)),
                   economy_workspace_layer=NS(cs2_feedback=BuyFeedback()),
                   setting_bool=lambda m,n,d: m.get_setting(n).value if m and m.get_setting(n) else d)
        commands = ClickGuiDrawList()
        clip = QRectF(10,10,180,80)
        append_buy_feedback(commands, owner, "ammo", QRectF(20,20,160,60), clip, 1, 1, 10)
        self.assertEqual(len(commands.rects), 1)
        self.assertEqual(len(commands.images), 1)
        self.assertEqual(commands.rects[0].fill.alpha(), 0)
        self.assertEqual(commands.rects[0].clip, clip)
        self.assertEqual(commands.images[0].clip, clip)
        registry.get("EconomyPanel").get_setting("CS2 Feedback").value = False
        disabled = ClickGuiDrawList()
        append_buy_feedback(disabled, owner, "ammo", QRectF(20,20,160,60), clip, 1, 1, 10)
        self.assertFalse(disabled.commands)


if __name__ == "__main__":
    unittest.main()
