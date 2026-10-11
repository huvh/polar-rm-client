"""Black-hole default, config migration and cached CPU/GPU wallpaper contracts.

Run: QT_QPA_PLATFORM=offscreen python tests/startup_black_hole_test.py
No robot, network, OpenGL context, video codec or generated artwork is needed.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication
from rm_client.config_store import apply_registry_config, export_client_config
from rm_client.model import build_default_registry
from rm_client.startup_wallpaper import StartupWallpaperManager

APP = QApplication.instance() or QApplication([])


class BlackHoleWallpaperTests(unittest.TestCase):
    def setUp(self):
        self.manager = StartupWallpaperManager(ROOT, assets_dir=ROOT / 'assets/wallpapers')
        self.addCleanup(self.manager.release)

    def test_default_and_reset_options(self):
        registry = build_default_registry()
        setting = registry.get('StartupVisual').get_setting('Wallpaper Profile')
        self.assertEqual(setting.value, 'BlackHole')
        self.assertEqual(self.manager.profile_names()[0], 'BlackHole')
        self.assertIn('BlackHole', setting.options)
        self.assertFalse(self.manager.can_remove('BlackHole'))
        shipped = json.loads((ROOT / 'configs/default.json').read_text())
        self.assertEqual(shipped['modules']['StartupVisual']['settings']['Wallpaper Profile'], 'BlackHole')
        self.assertEqual(shipped['startup_wallpaper_revision'], 1)

    def test_legacy_default_migrates_once_without_mutating_input(self):
        for old in ['TexasMP4', 'VendingMachine4K']:
            registry = build_default_registry()
            data = {'modules': {'StartupVisual': {'settings': {'Wallpaper Profile': old}}}}
            before = deepcopy(data)
            apply_registry_config(registry, data)
            setting = registry.get('StartupVisual').get_setting('Wallpaper Profile')
            self.assertEqual(setting.value, 'BlackHole')
            self.assertEqual(data, before)
            data['startup_wallpaper_revision'] = 1
            apply_registry_config(registry, data)
            self.assertEqual(setting.value, old)

    def test_custom_and_nonmedia_modes_stay_selected(self):
        for profile, mode in [('User:my-wallpaper', 'VideoParallax'), ('ParticleGrid', 'ParticleGrid'),
                              ('Default3000925581Pkg', 'PkgScene'), ('TexasMP4', 'ParticleGrid')]:
            registry = build_default_registry()
            visual = registry.get('StartupVisual')
            setting = visual.get_setting('Wallpaper Profile')
            setting.options.append('User:my-wallpaper')
            data = {'modules': {'StartupVisual': {'settings': {
                'Wallpaper Profile': profile, 'Background Mode': mode}}}}
            apply_registry_config(registry, data)
            self.assertEqual(setting.value, profile)
            self.assertEqual(visual.get_setting('Background Mode').value, mode)

    def test_export_remembers_migration_revision(self):
        data = export_client_config(build_default_registry(), gui_mode='JelloSigma',
                                    selected_category='System', selected_module='StartupVisual',
                                    module_expanded=set(), old_panels={}, new_panels={}, dropdown_panels={})
        self.assertEqual(data['startup_wallpaper_revision'], 1)

    def test_still_and_thumbnail_are_cached_without_decoder(self):
        with patch.object(self.manager.video_player, 'load', side_effect=AssertionError('decoder used')):
            frame = self.manager._black_hole_snapshot()
            self.assertIsNotNone(frame)
            self.assertEqual((frame.image.width(), frame.image.height()), (2560, 1440))
            self.assertFalse(frame.soft_glass.isNull())
            self.assertFalse(frame.glass.isNull())
            self.assertIs(frame, self.manager._black_hole_snapshot())
            thumb = self.manager.thumbnail('BlackHole')
            self.assertEqual(thumb.width(), 480)
            self.assertEqual(thumb.cacheKey(), self.manager.thumbnail('BlackHole').cacheKey())
            keys = []
            for width, height in [(1280,720), (1920,1080), (1024,768), (2560,1080)]:
                rect = QRectF(0,0,width,height)
                for mouse in [QPointF(0,0), QPointF(width,height)]:
                    for _ in range(8):
                        snapshot = self.manager.prepare_gpu_video(rect,mouse,1/30,mode='VideoParallax',
                            profile='BlackHole',parallax=60,zoom=1,high_res=True,motion_quality='Smooth60')
                    self.assertIs(snapshot, frame)
                    self.assertTrue(self.manager.last_draw_rect.contains(rect))
                    keys.append(snapshot.image.cacheKey())
                image = QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied)
                painter = QPainter(image)
                try:
                    self.assertTrue(self.manager.draw(painter,rect,mouse,1/60,mode='VideoParallax',
                        profile='BlackHole',parallax=60,zoom=1,dim=.28,high_res=True))
                finally:
                    painter.end()
                self.assertTrue(self.manager.last_draw_rect.contains(rect))
            self.assertEqual(len(set(keys)),1)
            self.assertIsNone(self.manager.video_player._thread)
            self.assertEqual(self.manager.glass_sequence, frame.sequence)

    def test_particle_and_cpu_gpu_switch_restore_static_glass(self):
        rect = QRectF(0,0,1280,720)
        mouse = QPointF(640,360)
        kwargs = dict(mode='VideoParallax',profile='BlackHole',parallax=22,zoom=1,
                      high_res=False,motion_quality='Smooth60')
        original = self.manager.prepare_gpu_video(rect,mouse,1/60,**kwargs)
        image = QImage(1280,720,QImage.Format.Format_ARGB32_Premultiplied)
        painter = QPainter(image)
        try:
            self.assertFalse(self.manager.draw(painter,rect,mouse,1/60,dim=.28,
                **{**kwargs,'profile':'ParticleGrid','mode':'ParticleGrid'}))
            self.assertTrue(self.manager.glass_frame.isNull())
            self.assertTrue(self.manager.draw(painter,rect,mouse,1/60,dim=.28,**kwargs))
            self.assertFalse(self.manager.glass_frame.isNull())
        finally:
            painter.end()
        snapshot = self.manager.prepare_gpu_video(rect,mouse,1/60,**kwargs)
        self.assertIs(snapshot, original)
        self.assertEqual(self.manager.last_frame.cacheKey(),original.image.cacheKey())
        self.assertEqual(self.manager.glass_frame.cacheKey(),original.glass.cacheKey())

    def test_missing_asset_falls_back_without_repeated_load(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = StartupWallpaperManager(ROOT, assets_dir=Path(directory))
            try:
                self.assertIsNone(manager._black_hole_snapshot())
                self.assertTrue(manager._black_hole_load_attempted)
                manager.last_frame = QImage(8,8,QImage.Format.Format_ARGB32_Premultiplied)
                manager.soft_glass_frame = manager.last_frame
                manager.glass_frame = manager.last_frame
                manager.transition_frame = manager.last_frame
                with patch('rm_client.startup_wallpaper.QImage', wraps=QImage) as image_constructor:
                    self.assertIsNone(manager._black_hole_snapshot())
                    self.assertIsNone(manager.prepare_gpu_video(QRectF(0,0,1280,720),QPointF(0,0),1/60,
                        mode='VideoParallax',profile='BlackHole',parallax=22,zoom=1,high_res=False,motion_quality='Smooth60'))
                    self.assertTrue(manager.last_frame.isNull())
                    self.assertTrue(manager.soft_glass_frame.isNull())
                    self.assertTrue(manager.glass_frame.isNull())
                    self.assertTrue(manager.transition_frame.isNull())
                    self.assertTrue(all(not call.args for call in image_constructor.call_args_list))
            finally:
                manager.release()


if __name__ == '__main__':
    unittest.main(verbosity=2)
