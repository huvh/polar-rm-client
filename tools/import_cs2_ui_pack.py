"""Read-only CS2 → local personal UI pack importer (never a game plug-in).

Requires an explicit Source2Viewer CLI, used ONLY on extracted copies. No Steam
process, game executable, memory, injection, install write, downloads or registry.
Run with this checkout's Python/PySide6. Personal output stays excluded from Git;
only a separately reviewed, authorized copy belongs under assets/cs2_ui_pack.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import wave
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

HUD = "panorama/images/hud/"
MEMBERS = {
    "dots": "panorama/images/backgrounds/bluedots_large_png.vtex_c",
    "skull": HUD + "teamcounter/teamcounter_skull_png.vtex_c",
    "skull_teammate": HUD + "teamcounter/teamcounter_skull-teammate_png.vtex_c",
    "alive_skull": HUD + "teamcounter/teamcounter_aliveskull_png.vtex_c",
    "alive_blue": HUD + "teamcounter/teamcounter_alivebgct_png.vtex_c",
    "alive_gold": HUD + "teamcounter/teamcounter_alivebgt_png.vtex_c",
    "money": HUD + "chevron_money.vsvg_c",
    "buy_icon": "panorama/images/icons/ui/buyzone.vsvg_c",
    "buy_ammo": "panorama/images/icons/equipment/ammobox.vsvg_c",
    "buy_recovery": "panorama/images/icons/equipment/healthshot.vsvg_c",
    "buy_revive": "panorama/images/icons/ui/refresh.vsvg_c",
    "kill_flag": "panorama/images/icons/ui/kill.vsvg_c",
    "elimination": "panorama/images/icons/ui/elimination.vsvg_c",
    "person": "panorama/images/icons/person.vsvg_c",
    **{f"sb_{name}": f"panorama/images/icons/ui/{name}.vsvg_c"
       for name in ("casual", "camera", "unmuted", "ct_silhouette", "menu")},
    "kill_mask": HUD + "kill_mask.vsvg_c",
    **{f"kill_{i}": HUD + f"kill_{i}.vsvg_c" for i in range(1, 6)},
    "kill_extra": HUD + "kill_extra.vsvg_c",
    **{f"kill_{kind}": HUD + f"kill_pip_{kind}.vsvg_c" for kind in ("default", "headshot", "blast")},
    # Resolved from the installed game_sounds_ui event table, not filenames
    # that merely sound relevant (store_item_purchased is the inventory store).
    "kill": "sounds/player/kill_doof_01.vsnd_c",
    "purchase": "sounds/ui/panorama/radial_menu_buy_03.vsnd_c",
    "cant_buy": "sounds/ui/weapon_cant_buy.vsnd_c",
    "buy_select": "sounds/ui/panorama/inventory_item_select_01.vsnd_c",
    "buy_hover": "sounds/ui/panorama/itemtile_rollover_09.vsnd_c",
}
STYLE_MEMBERS = (
    "panorama/styles/hud/hudteamcounter.vcss_c",
    "panorama/styles/hud/hudhealthammocenter.vcss_c",
    "panorama/styles/hud/huddeathnotice.vcss_c",
    "panorama/styles/buymenu.vcss_c",
    "soundevents/game_sounds_ui.vsndevts_c",
)
FONTS = {
    "font_medium": "stratum2-medium.otf",
    "font_condensed_regular": "stratum2condensed-regular.otf",
    "font_mono_regular": "stratum2mono-regular.otf",
    "font_regular": "stratum2-regular.otf",
    "font_bold": "stratum2-bold.otf",
    "font_condensed": "stratum2condensed-bold.otf",
    "font_mono": "stratum2mono-bold.otf",
    "font_timer": "stratum2_tf_bold.otf",
}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def vpk_index(path: Path) -> dict:
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("oversized VPK directory")
    data = path.read_bytes()
    magic, version, tree_size = struct.unpack_from("<III", data)
    if magic != 0x55AA1234 or version not in (1, 2) or len(data) > 32 * 1024 * 1024:
        raise ValueError("unsupported/oversized VPK directory")
    start = 12 if version == 1 else 28
    end = start + tree_size
    if end > len(data):
        raise ValueError("truncated VPK tree")
    pos = start
    def string():
        nonlocal pos
        stop = data.index(b"\0", pos, end)
        text = data[pos:stop].decode("utf-8")
        pos = stop + 1
        return text
    entries = {}
    while extension := string():
        while folder := string():
            while stem := string():
                crc, preload, archive, offset, length, terminator = struct.unpack_from("<IHHIIH", data, pos)
                pos += 18
                if terminator != 65535 or pos + preload > end:
                    raise ValueError("invalid VPK entry")
                head = data[pos:pos + preload]
                pos += preload
                name = ((folder + "/") if folder != " " else "") + stem
                if extension != " ":
                    name += "." + extension
                entries[name] = (crc, head, archive, offset, length, end)
    return entries


def extract_member(directory: Path, entry: tuple) -> bytes:
    crc, head, archive, offset, length, embedded = entry
    if length + len(head) > 16 * 1024 * 1024:
        raise ValueError("oversized selected resource")
    source = directory if archive == 32767 else directory.with_name(f"pak01_{archive:03}.vpk")
    with source.open("rb") as f:
        f.seek(offset + (embedded if archive == 32767 else 0))
        payload = head + f.read(length)
    if len(payload) != len(head) + length or zlib.crc32(payload) & 0xffffffff != crc:
        raise ValueError("selected VPK member checksum mismatch")
    return payload


def validate_destinations(game: Path, work: Path, output: Path, cli: Path) -> None:
    game, work, output, cli = (p.resolve() for p in (game, work, output, cli))
    if any(p.is_relative_to(game) for p in (work, output, cli)):
        raise ValueError("work, output and decompiler must be outside the CS2 installation")
    if game.is_relative_to(work) or game.is_relative_to(output):
        raise ValueError("destination must not contain the CS2 installation")
    if output.exists():
        raise ValueError("output must be a NEW directory; never overwrite a personal pack")
    if (work / "raw-selected").exists():
        raise ValueError("work/raw-selected must be new")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--game-root", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--cli", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv)
    game, work, cli, output = (x.resolve() for x in (args.game_root, args.work, args.cli, args.output))
    validate_destinations(game, work, output, cli)
    directory = game / "game/csgo/pak01_dir.vpk"
    font_source = game / "game/csgo/panorama/fonts/stratum2.uifont"
    entries = vpk_index(directory)
    selected = (*MEMBERS.values(), *STYLE_MEMBERS)
    missing = [s for s in selected if s not in entries]
    if missing:
        raise ValueError("This CS2 build lacks required UI resources: " + str(missing))
    sources = {directory, font_source}
    for member in selected:
        archive = entries[member][2]
        sources.add(directory if archive == 32767 else directory.with_name(f"pak01_{archive:03}.vpk"))
    before = {str(s.relative_to(game)): digest(s) for s in sorted(sources)}
    work.mkdir(parents=True, exist_ok=True)
    raw, export = work / "raw-selected", work / "export-selected"
    raw.mkdir(); export.mkdir()
    for member in selected:
        dest = raw / member
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(extract_member(directory, entries[member]))
    copied_font = raw / "stratum2.uifont"
    shutil.copyfile(font_source, copied_font)
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    def decompile(source: Path, dest: Path):
        # Never pass --game, a Steam VPK or an installed font to the decompiler.
        result = subprocess.run([str(cli), "-i", str(source), "-o", str(dest), "-d"],
                                cwd=work, capture_output=True, timeout=60, **flags)
        if result.returncode:
            raise RuntimeError(result.stderr.decode("utf-8", errors="replace")[-2000:])
        return result.stdout.decode("utf-8", errors="replace")
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    output.mkdir(parents=True)
    assets = {}
    for key, member in MEMBERS.items():
        suffix = ".svg" if member.endswith(".vsvg_c") else ".png" if member.endswith(".vtex_c") else ".wav"
        target = export / (key + suffix)
        decompile(raw / member, target)
        if not target.is_file() and suffix == ".png":
            # Embedded source PNGs retain their original name in VRF export.
            original = export / (Path(member).stem + ".png")
            if original.is_file():
                target = original
        if not target.is_file():
            raise ValueError("export did not produce " + target.name)
        dest = output / (key + (".png" if suffix == ".svg" else suffix))
        if suffix == ".svg":
            svg = QSvgRenderer(str(target))
            size = svg.defaultSize()
            if not svg.isValid() or size.isEmpty() or max(size.width(), size.height()) > 2048:
                raise ValueError("invalid SVG export")
            image = QImage(size * 3, QImage.Format_ARGB32_Premultiplied)
            image.fill(Qt.transparent)
            painter = QPainter(image)
            svg.render(painter, QRectF(0, 0, image.width(), image.height()))
            painter.end()
            if not image.save(str(dest)):
                raise ValueError("SVG raster export failed")
        else:
            shutil.copyfile(target, dest)
        if suffix == ".wav":
            with wave.open(str(dest), "rb") as sound:
                if sound.getcomptype() != "NONE" or sound.getsampwidth() != 2 or not sound.getnframes():
                    raise ValueError("non-PCM audio export")
        assets[key] = {"file": dest.name, "sha256": digest(dest), "source": member,
                       "source_sha256": digest(raw / member)}
    # This CLI exports font faces next to its INPUT, irrespective of -o. That
    # input is deliberately a copy in raw-selected, never the installed font.
    decompile(copied_font, export / "fonts")
    for key, name in FONTS.items():
        dest = output / name
        shutil.copyfile(raw / name, dest)
        assets[key] = {"file": name, "sha256": digest(dest),
                       "source": font_source.relative_to(game).as_posix(), "source_sha256": digest(copied_font)}
    for member in STYLE_MEMBERS:
        suffix = ".vsndevts" if member.endswith(".vsndevts_c") else ".css"
        decompile(raw / member, export / (Path(member).stem + suffix))
    after = {str(s.relative_to(game)): digest(s) for s in sorted(sources)}
    if before != after:
        raise RuntimeError("installed source hashes changed during import; pack NOT activated")
    manifest = {"schema": 1, "scope": "local-personal-use", "assets": assets,
                "source_files_before": before, "source_files_after": after,
                "decompiler_sha256": digest(cli), "decompiler": "ValveResourceFormat / Source2Viewer",
                "style_hashes": {s: digest(raw / s) for s in STYLE_MEMBERS}}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"assets": len(assets), "output": str(output), "source_hashes_unchanged": before == after}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
