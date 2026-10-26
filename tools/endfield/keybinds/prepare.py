"""只读校验本体VFS，准备键帽、键位弹窗和按钮原始曲线。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from tools.endfield.prepare_boot import decode


def key_icons():
    names = {letter.upper():letter for letter in "abcdefghijklmnopqrstuvwxyz"}
    names.update({str(number):f"alpha{number}" for number in range(10)})
    names.update({f"F{number}":f"f{number}" for number in range(1,13)})
    names.update(dict(Escape="esc",Space="space",Backspace="backspace",Tab="tab",
                     CapsLock="capslock",Enter="return",Shift="shift",RightShift="shift",
                     Ctrl="ctrl",CtrlRight="ctrl",Alt="alt",AltRight="altgr",Menu="menu",
                     MetaLeft="windows",MetaRight="rightwindows",Insert="insert",Delete="delete",
                     Home="home",End="end",PageUp="pageup",PageDown="pagedown",
                     Left="leftarrow",Right="rightarrow",Up="uparrow",Down="downarrow"))
    names.update(dict(zip("`-=[]\\;',./",("backquote","minus","equals","leftbracket","rightbracket",
                                           "backslash","semicolon","quote","comma","period","slash"))))
    return {key:"icon_key_"+name for key,name in names.items()}


def prepare(exports, output, index_path, game_vfs):
    rows = []
    for folder in exports:
        for line in (folder/"_index.jsonl").open(encoding="utf-8"):
            row = json.loads(line)
            for key in ("metadata_path","raw_path","output_path"):
                if row.get(key):
                    row[key] = str((folder/row[key]).resolve())
            rows.append(row)
    output.mkdir(parents=True,exist_ok=True)
    used, files = [], []
    icons = key_icons()
    textures = set(icons.values()) | {"pup_up_bg","pup_up_shadow","common_pop_up_logo","common_pop_up_text"}
    for name in sorted(textures):
        row = next(row for row in rows if row["type"] == "Texture2D" and str(row.get("name","")).casefold() == name.casefold())
        target = output/(name+".png")
        shutil.copyfile(row["output_path"],target)
        used.append(row)
        files.append({"file":target.name,"sha256":hashlib.sha256(target.read_bytes()).hexdigest(),
                      "bundle":row["source_path"],"object":row["path_id"]})
    clips = {}
    for name in ("gamesettingkeycodepopup_in","gamesettingkeycodepopup_out"):
        row = next(row for row in rows if row["type"] == "AnimationClip" and row.get("name") == name)
        data = decode(Path("."),row)
        clips[name] = {key:data[key] for key in ("m_FloatCurves","m_PositionCurves","m_ScaleCurves")}
        used.append(row)
    highlighted = next(row for row in rows if row["type"] == "AnimationClip" and row.get("name") == "Highlighted"
                       and "1c2508325848fea60fb8bea7" in row["source_path"])
    data = decode(Path("."),highlighted)
    used.append(highlighted)
    for suffix in ("/widgets/keysetting.prefab","/gamesettingkeycodepopuppanel.prefab"):
        used.append(next(row for row in rows if row["type"] == "GameObject"
                         and str(row.get("parent_asset_path","")).endswith(suffix)))
    verified = []
    wanted = {row["source_path"] for row in used}
    for block in json.loads(index_path.read_text(encoding="utf-8"))["blocks"]:
        for chunk in block["chunks"]:
            for entry in chunk["files"]:
                if entry["name"] not in wanted:
                    continue
                paths = list(game_vfs.glob("*/"+chunk["name"]))
                if len(paths) != 1:
                    raise ValueError("Cannot locate game chunk: "+chunk["name"])
                with paths[0].open("rb") as stream:
                    stream.seek(entry["offset"])
                    raw = stream.read(entry["length"])
                if hashlib.md5(raw).hexdigest() != bytes.fromhex(entry["file_data_md5"])[::-1].hex():
                    raise ValueError("Game bundle digest mismatch: "+entry["name"])
                verified.append({"bundle":entry["name"],"chunk":str(paths[0]),"offset":entry["offset"],
                                 "length":entry["length"],"sha256":hashlib.sha256(raw).hexdigest()})
    if len(verified) != len(wanted):
        raise ValueError("Not every source bundle was verified")
    config = {"schema":1,"icons":icons,"clips":clips,"key_control_size":[430,100],
              "key_line_size":[428,82],"key_font_size":25.55,"popup_size":[900,380],"title_font_size":36,
              "highlight_stream":data["m_MuscleClip"]["m_Clip"]["data"]["m_StreamedClip"],
              "highlight_duration":data["m_MuscleClip"]["m_StopTime"],"pressed_alpha":.1}
    (output/"source.json").write_text(json.dumps(config,ensure_ascii=False),encoding="utf-8")
    (output/"PROVENANCE.json").write_text(json.dumps({"files":files,"verified_game_bundles":verified},
                                                      ensure_ascii=False,indent=2),encoding="utf-8")
    (output/"NOTICE.txt").write_text("Original Arknights: Endfield key icons and animation data, extracted read-only from the user's installed game for local adaptation. Copyright belongs to their owners including HYPERGRYPH; excluded from the project's source-code license.\n",encoding="utf-8")
    manifest = {path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in output.iterdir()
                if path.is_file() and path.name != "MANIFEST.json"}
    (output/"MANIFEST.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    print(f"Prepared {len(icons)} key mappings; verified {len(verified)} installed-game bundles")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export",type=Path,action="append",required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--index",type=Path,required=True)
    parser.add_argument("--game-vfs",type=Path,required=True)
    args = parser.parse_args()
    prepare(args.export,args.out,args.index,args.game_vfs)
