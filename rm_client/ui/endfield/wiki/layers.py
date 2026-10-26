"""按本体RectTransform、九宫格和动画轨道绘制装饰及最近搜索。"""
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor
import math


def draw_tree(r, node, parent, unit=1, *, animation=None, root=None, at=None, opacity=1, clip=None, labels=None, sampler=None):
    if at is None:
        at = r.state.session_time
    if node.get("loop") in r.motion.durations:
        animation, root = node["loop"], node["path"]
        at = r.state.session_time%max(.001,r.motion.durations[animation])
        sampler = None
    root = node["path"] if root is None else root
    path = node["path"].removeprefix(root).lstrip("/")
    def sample(attribute, default):
        if sampler:
            return sampler(path,attribute,default)
        return r.motion.sample(animation, path, attribute, at, default) if animation else default
    t = node["transform"]
    amin, amax, pivot = (t[k] for k in ("m_AnchorMin", "m_AnchorMax", "m_Pivot"))
    pos, size = t["m_AnchoredPosition"], t["m_SizeDelta"]
    width = parent.width() * (amax["x"]-amin["x"]) + sample("m_SizeDelta.x", size["x"]) * unit
    height = parent.height() * (amax["y"]-amin["y"]) + sample("m_SizeDelta.y", size["y"]) * unit
    ax = parent.left() + parent.width() * (amin["x"]+(amax["x"]-amin["x"])*pivot["x"])
    ay = parent.top() + parent.height() * (1-amin["y"]-(amax["y"]-amin["y"])*pivot["y"])
    x = ax + sample("m_AnchoredPosition.x", pos["x"]) * unit - width*pivot["x"]
    y = ay - sample("m_AnchoredPosition.y", pos["y"]) * unit - height*(1-pivot["y"])
    rect = QRectF(x, y, width, height)
    if not node.get("active",True) and node["name"]!="BgHightLightImg":
        return rect
    if node["name"] == "BgHightLightImg" and not (labels or {}).get("_hover"):
        return rect
    opacity *= sample("m_Alpha", node["alpha"])
    if opacity <= .001:
        return rect
    color = node["color"]
    tint = QColor.fromRgbF(*(max(0,min(1,sample("m_Color."+c,color[c]))) for c in "rgb"))
    alpha = opacity * sample("m_Color.a", color["a"])
    if node.get("patches"):
        l, top, right, b = (v*unit for v in node["border"])
        xs, ys = (x,x+l,x+width-right,x+width), (y,y+top,y+height-b,y+height)
        for iy, keys in enumerate(node["patches"]):
            for ix, key in enumerate(keys):
                r._image(key,xs[ix],ys[iy],xs[ix+1]-xs[ix],ys[iy+1]-ys[iy],alpha,clip=clip,tint=tint)
    elif node.get("uv_scroll"):
        sx,sy = node["uv_scroll"]
        own = r._r(x,y,width,height)
        own = own if clip is None else clip.intersected(own)
        for iy in (-1,0,1):
            r._image(node["image"],x-((r.state.session_time*sx)%1)*width,
                     y+((r.state.session_time*sy)%1+iy)*height,width,height,alpha,clip=own,tint=tint)
    elif node.get("tile"):
        tw, th = (v*unit for v in node["tile"])
        own = r._r(x,y,width,height)
        tiled_clip = own if clip is None else clip.intersected(own)
        for iy in range(math.ceil(height/th)):
            for ix in range(math.ceil(width/tw)):
                r._image(node["image"],x+ix*tw,y+iy*th,tw,th,alpha,clip=tiled_clip,tint=tint)
    elif node.get("image"):
        r._image(node["image"],x,y,width,height,alpha,clip=clip,tint=tint)
    elif node.get("solid"):
        r._box(x,y,width,height,tint,alpha=alpha,clip=clip)
    if node.get("text") and labels and node["name"] in labels:
        text = node["text"]
        c = text["color"]
        tint = QColor.fromRgbF(*(c[channel] for channel in "rgb"))
        r._text(x,y,width,height,r._elide(labels[node["name"]],text["size"]*unit,width),
                text["size"]*unit,tint,bold=text["bold"],alpha=opacity*sample("m_fontColor.a",c["a"]),clip=clip)
    if node["mask"]:
        own = r._r(x,y,width,height)
        clip = own if clip is None else clip.intersected(own)
    for child in node["children"]:
        draw_tree(r,child,rect,unit,animation=animation,root=root,at=at,opacity=opacity,clip=clip,labels=labels,sampler=sampler)
    return rect


def draw_top_layer(r):
    # TopWidget高120，按本体与当前1920画布的.8比例适配，分割线正落在88px处。
    draw_tree(r,r.pack["layers"]["top"],QRectF(0,0,1920,96),.8)


def draw_scene_ground(r):
    """本体网格/噪声投影在地图和点环下面；相邻预投影帧按连续时钟混合。"""
    data = r.pack["layers"]["ground"]
    at = (r.state.session_time%data["period"])*data["fps"]
    index,blend = int(at),at%1
    r._image(data["frames"][index],*data["rect"])
    r._image(data["frames"][(index+1)%len(data["frames"])],*data["rect"],blend)


def draw_page_layers(r):
    data = r.pack["layers"]
    draw_top_layer(r)
    cx,cy,scale,alpha = r.background_projection
    draw_tree(r,data["bottom"],QRectF(cx-505*scale,cy-505*scale,1010*scale,1010*scale),scale,
              root="",opacity=alpha,sampler=lambda path,attribute,default:
              r.background.sample(r.motion,path,attribute,r.now,default))
    # 文字流和边角属于WikiPanel/Main/BgNode，分类页本体没有这一节点。
    if not r.view_category:
        draw_tree(r,data["frame"],QRectF(0,0,1920,1080),.8)
    # 场景材质以.2 UV/s流动；两份相邻投影实现Repeat，不在paint中生成或修改图片。
    phase = (r.state.session_time*data["scene_flow"]["uv_speed"])%1
    for y, rotation in ((85,180),):
        clip = r._r(0,y,1920,230)
        for tile in (0,1):
            r._image("scene_white_ground",(tile-phase)*1920,y,1920,230,.35,clip=clip,rotation=rotation)


def draw_history(r):
    tree = r.pack["layers"]["history"]
    parent = QRectF(0,0,1920,1080)
    title, cell = tree["children"][:2]
    shell = dict(tree,children=[])
    rect = draw_tree(r,shell,parent,.8)
    animation = "wiki_search_history_out" if r.state.search_closing_at is not None else "wiki_search_history_in"
    draw_tree(r,title,rect,.8,animation=animation,root="HistoryNode",at=r.search_at,
              labels={"TitleText":r._label("最近搜索","RECENT SEARCHES")})
    for index, term in enumerate(r.state.search_history):
        # 本体GridLayout：3列，551×68，间距11×14。
        offset = QRectF(rect).translated((index%3)*562*.8,(index//3)*82*.8)
        clip = r._r(99.2+(index%3)*449.6,187.2+(index//3)*65.6,440.8,54.4)
        bounds = draw_tree(r,cell,offset,.8,animation="wiki_search_historycell_in",root=cell["path"],at=r.search_at,
                          clip=clip,labels={"NameTxt":term,"_hover":clip.contains(r.host.hover_point)})
        r._hot(bounds.x(),bounds.y(),bounds.width(),bounds.height(),"wiki_history",term)
