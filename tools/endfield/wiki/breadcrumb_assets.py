"""离线提取 WikiTop 的路径状态、留白与原始九宫格，运行时只消费成品。"""
from __future__ import annotations

import hashlib
from tools.endfield.prepare_boot import decode


def prepare_breadcrumbs(root, rows, output, images, provenance):
    """按 Sprite 的实际裁切区域及 border 拆分，避免缩放小图损坏圆角。"""
    from PIL import Image

    prefab = "assets/beyond/dynamicassets/gameplay/ui/prefabs/wiki/widgets/wikitopwidget.prefab"
    objects = {}
    for row in rows:
        if row.get("parent_asset_path") == prefab and row["type"] in ("GameObject", "RectTransform", "MonoBehaviour"):
            try:
                objects[row["path_id"]] = decode(root, row)
            except (ValueError, KeyError):
                continue
    transforms = {key: value for key, value in objects.items() if "m_AnchoredPosition" in value}

    def components(transform):
        go = objects[transform["m_GameObject"]["m_PathID"]]
        return [objects.get(ref["component"]["m_PathID"], {}) for ref in go["m_Component"]]

    folder = next(t for t in transforms.values()
                  if objects[t["m_GameObject"]["m_PathID"]]["m_Name"] == "FolderCell")
    children = {objects[transforms[ref["m_PathID"]]["m_GameObject"]["m_PathID"]]["m_Name"]:
                transforms[ref["m_PathID"]] for ref in folder["m_Children"]}
    background = next(c for c in components(children["BgImg"]) if "m_Sprite" in c)
    highlight = next(c for c in components(children["BgHightLightImg"]) if "m_Sprite" in c)
    sprite_row = next(r for r in rows if r["type"] == "Sprite" and
                      r["path_id"] == background["m_Sprite"]["m_PathID"])
    sprite = decode(root, sprite_row)
    texture_row = next(r for r in rows if r["type"] == "Texture2D" and
                       r["path_id"] == sprite["m_RD"]["texture"]["m_PathID"])
    texture = Image.open(root / texture_row["output_path"]).convert("RGBA")
    rect, border = sprite["m_RD"]["textureRect"], sprite["m_Border"]
    x, y, width, height = (round(rect[k]) for k in ("x", "y", "width", "height"))
    source = texture.crop((x, texture.height - y - height, x + width, texture.height - y))
    left, bottom, right, top = (round(border[k]) for k in "xyzw")
    xs, ys = (0, left, width - right, width), (0, top, height - bottom, height)
    slices = []
    for row in range(3):
        keys = []
        for column in range(3):
            key = f"path_bg_{row}{column}"
            target = output / (key + ".png")
            source.crop((xs[column], ys[row], xs[column + 1], ys[row + 1])).save(target)
            images[key] = target.name
            keys.append(key)
            provenance.append({"output": target.name, "source": texture_row["parent_asset_path"],
                "texture_name": texture_row["name"], "bundle": texture_row["source_path"],
                "object": sprite_row["path_id"], "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "adaptation": "source Sprite textureRect crop and nine-slice border", "slice": [row, column]})
        slices.append(keys)
    states = next(c["states"] for c in components(folder) if "states" in c)
    padding = {state["stateName"]: next(d["layoutGroupPadding"] for d in state["descriptions"]
               if d["targetType"] == 12) for state in states}
    config = next(c["itemList"] for c in components(folder) if "itemList" in c)
    colors = {entry["name"]: entry["colorValue"] for entry in config}
    parent = transforms[folder["m_Father"]["m_PathID"]]
    spacing = next(c["m_Spacing"] for c in components(parent) if "m_Spacing" in c)
    text = next(c for c in components(children["NameTxt"]) if "m_fontSize" in c)

    def layer(name, graphic):
        return {"position": children[name]["m_AnchoredPosition"],
                "size_delta": children[name]["m_SizeDelta"], "color": graphic["m_Color"]}

    return {"slices": slices, "border": [left, top, right, bottom], "sprite_size": [width, height],
            "background": layer("BgImg", background), "highlight": layer("BgHightLightImg", highlight),
            "padding": padding, "spacing": spacing, "font_size": text["m_fontSize"],
            "current_color": colors["COLOR_CURRENT"], "parent_color": colors["COLOR_PARENT"]}
