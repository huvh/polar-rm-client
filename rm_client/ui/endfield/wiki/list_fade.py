"""用有序绘制指令的裁切/透明度带实现ScrollRect上下软遮罩，共用GPU和兼容路径。"""
from dataclasses import replace
from PySide6.QtCore import QRectF
from rm_client.ui.clickgui_gpu import GpuImage, GpuRect, GpuText


def fade_edges(draw_list, start, viewport, softness):
    bands = [(QRectF(viewport.left(),viewport.top()+softness,viewport.width(),viewport.height()-2*softness),1)]
    steps = max(1,round(softness))
    for index in range(steps):
        thickness = softness/steps
        alpha = (index+.5)/steps
        bands.extend(((QRectF(viewport.left(),viewport.top()+index*thickness,viewport.width(),thickness),alpha),
                      (QRectF(viewport.left(),viewport.bottom()-(index+1)*thickness,viewport.width(),thickness),alpha)))
    result = []
    for command in draw_list.commands[start:]:
        payload = command.payload
        for band, alpha in bands:
            clipped = band if payload.clip is None else band.intersected(payload.clip)
            if clipped.isEmpty() or not clipped.intersects(payload.rect):
                continue
            result.append(replace(command,payload=replace(payload,clip=clipped),opacity=command.opacity*alpha))
    draw_list.commands[start:] = result
    draw_list.commands[:] = [replace(c,sequence=i) for i,c in enumerate(draw_list.commands)]
    draw_list.rects[:] = [c.payload for c in draw_list.commands if isinstance(c.payload,GpuRect)]
    draw_list.texts[:] = [c.payload for c in draw_list.commands if isinstance(c.payload,GpuText)]
    draw_list.images[:] = [c.payload for c in draw_list.commands if isinstance(c.payload,GpuImage)]
