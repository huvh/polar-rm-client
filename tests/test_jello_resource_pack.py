"""Function-owned Jello assets, old caller seams, and real portable staging."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('POLAR_DISABLE_MEDIA_PRELOAD','1')
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication
from rm_client.runtime_paths import RuntimePaths
from rm_client.model import build_default_registry
from rm_client.ui.jello.resources import FONTS, IMAGES, LEGACY_FILES, MANIFEST, SOUNDS, JelloResources
from rm_client.ui.fonts import FontBook
from rm_client.ui.jello_clickgui import JelloClickGuiRenderer, JelloClickGuiState
from rm_client.ui.polar.window_assembly import resolve_client_asset
from rm_client.ui_audio import ReliableAudioPool, UiAudioManager
from tools.jello.pack import stage, validate

APP=QApplication.instance() or QApplication([])
PACK=ROOT/'rm_client/ui/jello'


class ResourcePackTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def test_complete_existing_inventory_and_functional_ownership(self):
        self.assertEqual(validate(PACK),{'status':'JELLO_PACK_VALID','files':24})
        self.assertEqual((len(IMAGES),len(FONTS),len(SOUNDS)),(13,3,8))
        data=json.loads((PACK/MANIFEST).read_text(encoding='utf-8'))
        self.assertEqual(data['migration_base'],'5bb0ec263757be013b9edfd0225c671de6facf1e')
        self.assertEqual({p.split('/')[0] for p in data['files']},
                         {'clickgui','widgets','scrolling','shadows','hud','typography','audio'})
        for old,new in LEGACY_FILES.items():
            self.assertEqual(data['files'][new]['legacy_path'],old)
            self.assertFalse((ROOT/old).is_file(),old+' was copied instead of moved')

    def test_source_and_frozen_paths_do_not_read_private_overrides(self):
        source=RuntimePaths.discover(module_file=ROOT/'rm_client/runtime_paths.py',frozen=False,environ={})
        self.assertEqual(source.jello_pack,PACK)
        frozen=RuntimePaths.discover(executable=self.root/'portable/POLAR-RM.exe',frozen=True,environ={})
        self.assertEqual(frozen.jello_pack,self.root/'portable/resources/assets/jello')
        stage(PACK,frozen.jello_pack)
        for paths in (source,frozen):
            resources=JelloResources.for_workspace(paths.resource_root)
            for name in IMAGES:self.assertFalse(QImage(str(resources.image(name))).isNull(),name)
            for name in FONTS:
                self.assertGreaterEqual(QFontDatabase.addApplicationFont(str(resources.font(name))),0,name)
            book=FontBook()
            book.load_from_project_assets(paths.resource_root,keys=('jello_light','jello_medium','jello_regular'))
            self.assertEqual(set(book.loaded),{'jello_light','jello_medium','jello_regular'})
            pool=SimpleNamespace(root=paths.asset('ui_sounds'),custom_root=None)
            for name in UiAudioManager.JELLO_SOUNDS:
                self.assertEqual(ReliableAudioPool._sound_path(pool,name),resources.sound(Path(name).name))

    def test_old_explicit_image_root_resolves_only_its_adjacent_package(self):
        old=JelloResources.from_image_root(ROOT/'assets/jello')
        self.assertEqual(old.root,PACK)
        plain=JelloClickGuiRenderer(ROOT/'assets/jello')
        owned=JelloClickGuiRenderer(PACK)
        self.assertEqual(plain.image_assets,owned.image_assets)
        missing=JelloResources.from_image_root(self.root/'missing-theme-assets/jello')
        self.assertEqual(missing.image('options.png'),self.root/'missing-theme-assets/jello/options.png')
        self.assertFalse(missing.packaged)

    def test_fonts_and_legacy_audio_event_ids_keep_same_exact_resources(self):
        book=FontBook();book.load_from_project_assets(ROOT,keys=('jello_light','jello_medium','jello_regular'))
        self.assertTrue({'jello_light','jello_medium','jello_regular'}<=book.loaded.keys())
        self.assertEqual(book.font('jello_light',18).styleName(),'Light')
        self.assertEqual(book.font('jello_medium',18).styleName(),'Medium')
        class PoolPaths:
            root=ROOT/'assets/ui_sounds'
            custom_root=None
        for name in UiAudioManager.JELLO_SOUNDS:
            self.assertEqual(ReliableAudioPool._sound_path(PoolPaths(),name),PACK/SOUNDS[Path(name).name])
        # Caller-owned unrelated pools retain the original explicit root.
        pool=PoolPaths();pool.root=self.root
        self.assertEqual(ReliableAudioPool._sound_path(pool,'jello/activate.mp3'),self.root/'jello/activate.mp3')

    def test_release_staging_only_copies_manifested_materials_and_never_overwrites(self):
        destination=self.root/'portable/assets/jello'
        result=stage(PACK,destination);self.assertEqual(result['files'],24)
        self.assertEqual({p.relative_to(destination).as_posix() for p in destination.rglob('*') if p.is_file()},
                         set(LEGACY_FILES.values())|{MANIFEST})
        for relative in LEGACY_FILES.values():
            self.assertEqual((PACK/relative).read_bytes(),(destination/relative).read_bytes())
        with self.assertRaises(ValueError):stage(PACK,destination)

    def test_tampering_and_unlisted_resource_fail_validation(self):
        destination=self.root/'pack';stage(PACK,destination)
        name=next(iter(IMAGES.values()));target=destination/name
        original=target.read_bytes();target.write_bytes(original+b'changed')
        with self.assertRaises(ValueError):validate(destination)
        target.write_bytes(original)
        extra=destination/'widgets/assets/extra.png';extra.write_bytes(original)
        with self.assertRaises(ValueError):validate(destination)

    def test_preloaded_widget_shadows_do_not_decode_again_during_repeated_paint(self):
        from rm_client.ui import jello_widgets
        jello_widgets.shadow_images.cache_clear()
        with patch('rm_client.ui.jello_widgets.RuntimePaths.discover',return_value=
                   RuntimePaths.discover(module_file=ROOT/'rm_client/runtime_paths.py',frozen=False,environ={})):
            shadows=jello_widgets.shadow_images()
            self.assertTrue(all(not image.isNull() for image in shadows.values()))
            image=QImage(400,300,QImage.Format_ARGB32_Premultiplied);p=QPainter(image)
            try:
                with patch('rm_client.ui.jello_widgets.QImage',side_effect=AssertionError('No paint decode')):
                    for _ in range(100):jello_widgets.draw_shadow(p,QRectF(40,40,240,160))
            finally:p.end()

    def test_hud_alias_uses_same_owned_pack_as_clickgui_and_controls(self):
        paths=RuntimePaths.discover(module_file=ROOT/'rm_client/runtime_paths.py',frozen=False,environ={})
        self.assertEqual(resolve_client_asset(paths,'assets','jello','hud_shadow.png'),PACK/IMAGES['hud_shadow.png'])
        self.assertEqual(resolve_client_asset(paths,'assets','jello','check.png'),PACK/IMAGES['check.png'])

    def test_flat_original_and_function_pack_render_identical_raster_frames(self):
        """Compare decoded materials in real QPainter, not a mocked draw list.

        This is an offline raster equality check, not native GPU acceptance.
        """
        flat=self.root/'original-images';flat.mkdir()
        for name,relative in IMAGES.items():
            (flat/name).write_bytes((PACK/relative).read_bytes())
        original=JelloClickGuiRenderer(flat)
        packaged=JelloClickGuiRenderer(PACK)
        fonts=FontBook();fonts.load_from_project_assets(ROOT)
        host=SimpleNamespace(registry=build_default_registry(),font=fonts.font,
            hover_point=QPointF(-1,-1),gui_visible=True,
            current_profile=lambda:'resource-migration',hotspots=[],gui_scroll_viewports=[])
        host.add_hotspot=lambda *args,**kwargs:None
        for width,height,dpr in ((960,540,2),(1280,720,1),(1600,900,1.5),(2560,1440,1)):
            for language in ('English','简体中文'):
                host.registry.get('ClickGui').get_setting('Language').value=language
                for module in (None,'HUD'):
                    with self.subTest(size=(width,height),dpr=dpr,language=language,module=module):
                        images=[]
                        for renderer in (original,packaged):
                            state=JelloClickGuiState()
                            if module:
                                state.open_settings(module)
                                state.settings_panel_animation.reset(1)
                                state.settings_background_animation.reset(1)
                            image=QImage(round(width*dpr),round(height*dpr),QImage.Format_ARGB32_Premultiplied)
                            image.setDevicePixelRatio(dpr);image.fill(Qt.GlobalColor.transparent)
                            painter=QPainter(image)
                            try:renderer.paint_compat(host,state,painter,width,height,1)
                            finally:painter.end()
                            images.append(image)
                        self.assertEqual(images[0],images[1])
                        self.assertGreater(images[1].pixelColor(width//2,height//2).alpha(),0)


if __name__=='__main__':unittest.main()
