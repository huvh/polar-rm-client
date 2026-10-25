"""Bundle reviewed scoreboard exports from OFFLINE COPIES, never a game path.

Input layout: raw/, export/, metadata_compat_copy/. VRF 20.0 cannot parse the
new RED2 editor KV3. Its analysis copies omit only that block; DATA, SrMa and
LaCo must be byte-identical to the originals before an export is accepted.
No extraction, process access, network, or game execution happens here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct

SOURCES = {
    'scoreboard.css': 'panorama/styles/scoreboard.vcss_c',
    'scoreboard.xml': 'panorama/layout/scoreboard.vxml_c',
    'scoreboard_owner.xml': 'panorama/layout/scoreboard_owner.vxml_c',
    'scoreboard.ts': 'panorama/scripts/scoreboard.vts_c',
    'csgostyles.css': 'panorama/styles/csgostyles.vcss_c',
}
ICONS = ('casual', 'camera', 'unmuted', 'ct_silhouette', 'menu',
         'competitive', 'ping_4', 'stats', 'elimination')
FONTS = {'font_medium': 'stratum2-medium.otf',
         'font_condensed_regular': 'stratum2condensed-regular.otf',
         'font_mono_regular': 'stratum2mono-regular.otf'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def blocks(path):
    data = path.read_bytes()
    size, version, _, offset, count = struct.unpack_from('<IHHII', data)
    if size != len(data) or version != 12 or count > 32:
        raise ValueError('Invalid copied resource header')
    result = {}
    for index in range(count):
        at = 8 + offset + index * 12
        name, relative, length = struct.unpack_from('<4sII', data, at)
        start = at + 4 + relative
        if start + length > len(data):
            raise ValueError('Invalid resource block')
        result[name.decode('ascii')] = data[start:start + length]
    return result


def bundle(reference, asset_root):
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    reference, asset_root = reference.resolve(), asset_root.resolve()
    if asset_root.is_relative_to(reference) or reference.is_relative_to(asset_root):
        raise ValueError('Input copies and bundled assets must be separate')
    pack = asset_root / 'cs2_ui_pack'
    source = asset_root / 'cs2_scoreboard_source'
    manifest = json.loads((pack / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['scope'] != 'authorized-distribution':
        raise ValueError('This bundler requires the reviewed redistribution pack')
    provenance = {'schema': 1, 'scope': manifest['scope'],
                  'source_snapshot': 'installed CS2 selected copies 2026-10-25',
                  'decompiler': 'Source2Viewer 20.0.0.0, offline copies only',
                  'analysis_transform': 'RED2 editor metadata omitted ONLY in analysis copies; non-RED2 payloads verified identical',
                  'assets': {}}
    source.mkdir(exist_ok=True)
    for name, member in SOURCES.items():
        original = reference / 'raw' / Path(member).name
        compat = reference / 'metadata_compat_copy' / Path(member).name
        before, after = blocks(original), blocks(compat)
        if {k: v for k, v in before.items() if k != 'RED2'} != after:
            raise ValueError('Resource content changed in analysis copy: ' + member)
        export = reference / 'export' / name
        if not export.is_file() or export.stat().st_size < 100:
            raise ValueError('Decompiler did not produce ' + name)
        shutil.copyfile(export, source / name)
        provenance['assets'][name] = {'source': member, 'source_sha256': digest(original),
                                    'sha256': digest(export),
                                    'content_blocks': {k: hashlib.sha256(v).hexdigest() for k, v in after.items()}}
    for icon in ICONS:
        original = reference / 'raw' / (icon + '.vsvg_c')
        compat = reference / 'metadata_compat_copy' / original.name
        before, after = blocks(original), blocks(compat)
        if {k: v for k, v in before.items() if k != 'RED2'} != after:
            raise ValueError('SVG content changed in analysis copy: ' + icon)
        export = reference / 'export' / (icon + '.svg')
        svg = QSvgRenderer(str(export))
        if not svg.isValid():
            raise ValueError('Invalid exported SVG: ' + icon)
        image = QImage(96, 96, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        p = QPainter(image)
        svg.render(p, QRectF(0, 0, 96, 96))
        p.end()
        dest = pack / ('sb_' + icon + '.png')
        if not image.save(str(dest)):
            raise ValueError('Failed raster export')
        entry = {'source': 'panorama/images/icons/ui/' + original.name,
                 'source_sha256': digest(original), 'sha256': digest(dest), 'file': dest.name}
        manifest['assets']['sb_' + icon] = entry
        shutil.copyfile(export, source / export.name)
        provenance['assets'][export.name] = {**entry, 'sha256': digest(export)}
    for key, name in FONTS.items():
        export = reference / 'raw' / name
        shutil.copyfile(export, pack / name)
        manifest['assets'][key] = {'file': name, 'sha256': digest(export),
                                   'source': 'game/csgo/panorama/fonts/stratum2.uifont',
                                   'source_sha256': digest(reference / 'raw/stratum2.uifont')}
    (pack / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (source / 'provenance.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--asset-root', type=Path, required=True)
    args = parser.parse_args()
    bundle(args.reference_root, args.asset_root)
