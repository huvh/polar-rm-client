"""Wiki顶部、底部及搜索历史的离线层级/纹理提取。"""
from __future__ import annotations

import hashlib
from tools.endfield.prepare_boot import decode
from tools.endfield.wiki.wave_assets import prepare_waves


def prepare_layers(root, rows, output, images, provenance):
    from PIL import Image, ImageChops
    by_id = {r["path_id"]: r for r in rows if "path_id" in r}
    cache = {}

    def texture(graphic, key):
        sprite_id = graphic.get("m_Sprite", {}).get("m_PathID", 0)
        reference = str(graphic.get("imgRefPath", "")).lower() if graphic.get("imgUsePathReference") else ""
        if reference:
            sprite_id = next((r["path_id"] for r in rows if r.get("type") == "Sprite"
                              and str(r.get("parent_asset_path", "")).lower() == reference), sprite_id)
        if sprite_id:
            if sprite_id not in by_id:
                raise ValueError(f"Wiki layer Sprite missing: {sprite_id}; export its game dependency bundle")
            sprite = decode(root, by_id[sprite_id])
            texture_id = sprite["m_RD"]["texture"]["m_PathID"]
        else:
            sprite = None
            texture_id = graphic.get("m_Texture", {}).get("m_PathID", 0)
            material = by_id.get(graphic.get("m_Material", {}).get("m_PathID"))
            if not texture_id and material:
                props = decode(root, material)["m_SavedProperties"]
                texture_id = next((v["m_Texture"]["m_PathID"] for k, v in props["m_TexEnvs"]
                                   if k == "_MainTex"), 0)
        if not texture_id or texture_id not in by_id:
            return {}
        identity = sprite_id, texture_id
        if identity in cache:
            return cache[identity]
        row = by_id[texture_id]
        source = Image.open(root / row["output_path"]).convert("RGBA")
        material_row = by_id.get(graphic.get("m_Material",{}).get("m_PathID"))
        text_scroll = material_row and material_row.get("name")=="M_text_scroll_blcak"
        if text_scroll:
            # 源材质极低RGB强度配合预乘混合，文字呈黑色；保留原贴图的透明度。
            dark = Image.new("RGBA",source.size,(0,0,0,0))
            dark.putalpha(source.getchannel("A"))
            source = dark
        border = [0, 0, 0, 0]
        if sprite:
            rect = sprite["m_RD"]["textureRect"]
            x, y, w, h = (round(rect[k]) for k in ("x", "y", "width", "height"))
            source = source.crop((x, source.height-y-h, x+w, source.height-y))
            b = sprite["m_Border"]
            border = [round(b[k]) for k in "xwzy"]
        def save(name, image):
            target = output / (name + ".png")
            image.save(target)
            images[name] = target.name
            provenance.append({"output": target.name, "source": row.get("parent_asset_path"),
                "texture_name": row.get("name"), "bundle": row["source_path"], "object": row["path_id"],
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "adaptation": "source Sprite crop / border preserved"})
        result = {"image": key, "size": list(source.size)}
        if text_scroll:
            props = decode(root,material_row)["m_SavedProperties"]
            speed = dict(props["m_Colors"])["_MainTexUVSpeed"]
            result["uv_scroll"] = [speed["r"],speed["g"]]
        save(key, source)
        if text_scroll:
            provenance[-1]["adaptation"] = "source text alpha and black material intensity; runtime UV scroll"
            provenance[-1]["dependencies"] = [{"source":material_row["parent_asset_path"],"bundle":material_row["source_path"],"object":material_row["path_id"]}]
        if any(border) and graphic.get("m_Type") == 1:
            l, t, r, b = border
            xs, ys = (0, l, source.width-r, source.width), (0, t, source.height-b, source.height)
            if min(xs[i+1]-xs[i] for i in range(3)) > 0 and min(ys[i+1]-ys[i] for i in range(3)) > 0:
                result["border"] = border
                result["patches"] = [[f"{key}_{y}{x}" for x in range(3)] for y in range(3)]
                for y in range(3):
                    for x in range(3):
                        save(result["patches"][y][x], source.crop((xs[x], ys[y], xs[x+1], ys[y+1])))
        cache[identity] = result
        return result

    def tree(suffix, target):
        objects = {}
        for row in rows:
            if str(row.get("parent_asset_path", "")).endswith("/"+suffix) and row["type"] in ("GameObject", "RectTransform", "MonoBehaviour"):
                try:
                    objects[row["path_id"]] = decode(root, row)
                except (ValueError, KeyError):
                    continue
        transforms = {k: v for k, v in objects.items() if "m_AnchoredPosition" in v}
        def node(key, path=""):
            tr = transforms[key]
            go = objects[tr["m_GameObject"]["m_PathID"]]
            path = (path+"/"+go["m_Name"]).strip("/")
            comps = [objects.get(r["component"]["m_PathID"], {}) for r in go["m_Component"]]
            graphic = next((c for c in comps if "m_Sprite" in c or "m_Texture" in c), {})
            text = next((c for c in comps if "m_fontSize" in c), {})
            loop = next((c["_animationLoop"]["m_PathID"] for c in comps if c.get("_animationLoop", {}).get("m_PathID")), 0)
            result = {"path": path, "name": go["m_Name"], "active":bool(go["m_IsActive"]), "transform": {k: tr[k] for k in
                ("m_AnchorMin", "m_AnchorMax", "m_AnchoredPosition", "m_SizeDelta", "m_Pivot")},
                "color": graphic.get("m_Color", dict(r=1,g=1,b=1,a=1)),
                "alpha": next((c["m_Alpha"] for c in comps if "m_Alpha" in c), 1),
                "mask": next((True for c in comps if "m_Softness" in c), False),
                "solid": bool(graphic and not graphic.get("m_Material", {}).get("m_PathID")),
                "loop": by_id.get(loop, {}).get("name"),
                "children": [node(r["m_PathID"], path) for r in tr["m_Children"] if r["m_PathID"] in transforms]}
            if graphic:
                result.update(texture(graphic, "layer_"+str(key).replace("-", "n")))
                if graphic.get("m_Type") == 2 and result.get("size"):
                    result["tile"] = [v/max(.001,graphic.get("m_PixelsPerUnitMultiplier",1)) for v in result["size"]]
            if text:
                result["text"] = {"size": text["m_fontSize"], "color": text["m_fontColor"], "bold": text["m_fontWeight"] >= 600}
            return result
        key = next(k for k,t in transforms.items() if objects[t["m_GameObject"]["m_PathID"]]["m_Name"] == target)
        return node(key)

    bottom = tree("wiki_uideco.prefab", "ButtomDecoLayout ")
    def prefix(node):
        node["path"] = "HudNode/" + node["path"]
        for child in node["children"]:
            prefix(child)
    prefix(bottom)
    # 场景白色流动地面材质的主贴图/遮罩及UV速度，烘焙为Qt可用的二维投影。
    main = next(r for r in rows if r.get("type") == "Texture2D" and r.get("name") == "T_fx_mask_1123_M")
    mask = next(r for r in rows if r.get("type") == "Texture2D" and r.get("name") == "T_fx_mask_1124_M")
    material = next(r for r in rows if r.get("type") == "Material" and r.get("name") == "M_fxui_wiki_white_ground_01")
    colors = dict(decode(root,material)["m_SavedProperties"]["m_Colors"])
    wave = Image.open(root/main["output_path"]).convert("L").resize((512,128))
    wave_mask = Image.open(root/mask["output_path"]).convert("L").resize(wave.size)
    projected = Image.new("RGBA",wave.size,(255,255,255,255))
    # 3D地面在二维投影两端羽化，防止投影矩形留下横向硬边。
    feather = Image.new("L",wave.size)
    feather.putdata([round(255*min(1,y/24,(wave.height-1-y)/24))
                     for y in range(wave.height) for _ in range(wave.width)])
    projected.putalpha(ImageChops.multiply(ImageChops.multiply(wave,wave_mask),feather))
    path = output/"scene_white_ground.png"
    projected.save(path)
    images["scene_white_ground"] = path.name
    provenance.append({"output":path.name,"source":main["parent_asset_path"],"texture_name":main["name"],
        "bundle":main["source_path"],"object":main["path_id"],"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
        "adaptation":"2D projection of source white-ground main/mask; source material UV speed",
        "dependencies":[{"source":r["parent_asset_path"],"bundle":r["source_path"],"object":r["path_id"]}
                        for r in (mask,material)]})
    return {"top": tree("wikitopwidget.prefab", "DecoNode"),
            "frame": tree("wikipanel.prefab", "BgNode"),
            "bottom": bottom,
            "history": tree("wikisearchpanel.prefab", "HistoryNode"),
            "scroll": {"softness_y": 10, "deceleration": .135, "drag_threshold": 6},
            "scene_flow": {"uv_speed": colors["_MainTexUVSpeed"]["r"],
                           "offset_speed": colors["_OffsetSpeed"]["g"]},
            "ground": prepare_waves(root,rows,output,images,provenance),
            "blur_radius": 72}
