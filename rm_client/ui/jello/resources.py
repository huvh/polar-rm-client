"""Small pure-path catalog shared by Jello UI and portable packaging.

No Qt/database, game installation, network, directory scan or user-data writes.
Callers preload at construction; image/audio drawing reuses these paths.
"""
from dataclasses import dataclass
from pathlib import Path

MANIFEST = 'JELLO_RESOURCES.json'

# Key is the existing public resource name. Values encode functional ownership.
IMAGES = {
    'options.png': 'clickgui/assets/options.png',
    'check.png': 'widgets/assets/check.png',
    'verticalscrollbartop.png': 'scrolling/assets/verticalscrollbartop.png',
    'verticalscrollbarbottom.png': 'scrolling/assets/verticalscrollbarbottom.png',
    'hud_shadow.png': 'hud/assets/hud_shadow.png',
    **{name+'.png': 'shadows/assets/'+name+'.png' for name in (
        'shadow_corner','shadow_corner_2','shadow_corner_3','shadow_corner_4',
        'shadow_left','shadow_right','shadow_top','shadow_bottom')},
}
FONTS = {name: 'typography/assets/'+name for name in (
    'Jello-Helvetica-Neue-Light.ttf','Jello-Helvetica-Neue-Medium.ttf','Jello-Regular.ttf')}
SOUNDS = {name+'.mp3': 'audio/assets/'+name+'.mp3' for name in (
    'activate','click','clicksound','connect','deactivate','error','pop','switch')}
LEGACY_FILES = {
    **{'assets/jello/'+name: relative for name,relative in IMAGES.items()},
    **{'assets/fonts/'+name: relative for name,relative in FONTS.items()},
    **{'assets/ui_sounds/jello/'+name: relative for name,relative in SOUNDS.items()},
}


@dataclass(frozen=True)
class JelloResources:
    root: Path
    packaged: bool = True

    @classmethod
    def from_image_root(cls, root):
        """Accept the old explicit assets/jello constructor seam during migration.

        Only that exact legacy project layout redirects to its adjacent owned
        package. An arbitrary missing/test/private directory stays missing;
        it must not silently select another installation's assets.
        """
        root = Path(root)
        if (root/MANIFEST).is_file():
            return cls(root)
        if root.name == 'jello' and root.parent.name == 'assets':
            owned = root.parent.parent/'rm_client/ui/jello'
            if (owned/MANIFEST).is_file():
                return cls(owned)
        return cls(root,False)

    @classmethod
    def for_workspace(cls, workspace):
        workspace = Path(workspace)
        source = workspace/'rm_client/ui/jello'
        if (source/MANIFEST).is_file():
            return cls(source)
        return cls.from_image_root(workspace/'assets/jello')

    def image(self, name):
        return self.root/(IMAGES[name] if self.packaged else name)

    def font(self, name):
        return self.root/FONTS[name]

    def sound(self, name):
        return self.root/SOUNDS[name]
