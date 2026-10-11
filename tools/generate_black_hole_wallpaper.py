"""Rebuild POLAR's original black-hole wallpaper (no downloaded artwork).

Development-only dependencies: numpy and Pillow. The client ships the resulting
PNG and never runs this generator. Fixed seed makes the artwork reproducible.
"""
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter


def generate(width=2560, height=1440):
    rng = np.random.default_rng(20261011)
    y, x = np.mgrid[:height, :width].astype(np.float32)
    x /= width; y /= height
    # Leave the left launcher column quiet. The subject stays inside 4:3 crops.
    px = (x - .655) * width / height
    py = y - .415
    angle = -.12
    u = px * np.cos(angle) + py * np.sin(angle)
    v = -px * np.sin(angle) + py * np.cos(angle)
    r = np.sqrt(u*u + v*v)
    theta = np.arctan2(v, u)
    rgb = np.zeros((height,width,3), np.float32)
    rgb[:] = [.006,.012,.023]
    haze = np.exp(-((u/.60)**2 + (v/.23)**2))
    rgb += haze[...,None] * [.015,.026,.050]
    # Receding nebula filaments, deliberately subdued behind the menu.
    cloud = (np.sin(13*u + 2*np.sin(9*v)) + np.sin(23*v+4*u))*.5
    rgb += (haze*(cloud+1)*.009)[...,None] * [.35,.52,1.0]
    # Sparse, subpixel-soft stars. Avoid the actual event horizon.
    for _ in range(950):
        sx,sy = rng.integers(0,width),rng.integers(0,height)
        brightness = rng.uniform(.07,.33)
        radius = 1 if rng.random()<.975 else 2
        for dy in range(-radius,radius+1):
            for dx in range(-radius,radius+1):
                xx,yy=sx+dx,sy+dy
                if 0<=xx<width and 0<=yy<height:
                    rgb[yy,xx] += brightness*np.exp(-(dx*dx+dy*dy)/.62)*np.array([.67,.79,1])
    radius=.151
    # Gravitationally lensed rear disk: a broad gold arch outside the shadow.
    ring_width=.010 + .013*(.5-.5*np.sin(theta))
    ring=np.exp(-((r-radius-.011)/ring_width)**2)
    fine=.76+.12*np.sin(r*3700+8*np.sin(theta*3))+.07*np.sin(r*7200+theta*13)
    doppler=.62+.53*np.clip(-u/.30,0,1)
    rgb += (ring*fine*doppler)[...,None]*[1.35,.68,.24]
    rgb += (np.exp(-((r-radius-.015)/.047)**2)*.17)[...,None]*[1,.37,.10]
    # Oblate accretion disk, with many fine orbital filaments and asymmetric light.
    disk_r=np.sqrt(u*u+(v/.15)**2)
    disk_theta=np.arctan2(v/.15,u)
    inner=np.clip((disk_r-.172)/.035,0,1)
    envelope=inner*np.exp(-((disk_r-.22)/.34)**2)
    structure=(.69+.13*np.sin(disk_r*820+3*np.sin(disk_theta*6))
               +.08*np.sin(disk_r*1910+disk_theta*19)
               +.07*np.sin(disk_r*3400+5*np.sin(disk_theta*8)))
    disk=envelope*structure*(.85+.42*np.clip(-u/.5,-1,1))
    disk*=np.where(v<0,np.clip((r-radius)/.012,0,1),1)
    rgb += disk[...,None]*[1.45,.75,.29]
    # Jet-thin equatorial glow and diffuse bloom, fading before the left text.
    streak=np.exp(-(v/.007)**2)*np.exp(-(u/.73)**2)
    streak*=np.clip((np.abs(u)-radius)/.07,0,1)
    rgb += streak[...,None]*[.92,.46,.19]
    # The shadow is opaque; its crisp inner photon ring stays legible at 720p.
    shadow=np.clip((r-radius+.002)/.006,0,1)
    rgb *= shadow[...,None]
    photon=np.exp(-((r-radius-.003)/.0016)**2)
    rgb += (photon*(.65+.35*(-np.sin(theta)*.5+.5)))[...,None]*[1.15,.86,.53]
    # Cinematic bloom is baked once, never recomputed in the UI render loop.
    light=Image.fromarray(np.uint8(np.clip(rgb,0,1)*255),'RGB')
    bloom=np.asarray(light.filter(ImageFilter.GaussianBlur(16)),dtype=np.float32)/255
    rgb += bloom*.20
    # A natural edge falloff and dark left rail keep launcher typography crisp.
    vignette=np.clip(1-.36*((x-.52)**2+(y-.45)**2),.65,1)
    left=.40+.60/(1+np.exp(-(x-.30)*15))
    rgb*= (vignette*left)[...,None]
    rgb=1-np.exp(-rgb*1.30)
    rgb=np.power(np.clip(rgb,0,1),.91)
    return Image.fromarray(np.uint8(rgb*255),'RGB')


if __name__ == '__main__':
    target=Path(__file__).resolve().parents[1]/'assets/wallpapers/builtin/black-hole.png'
    target.parent.mkdir(parents=True,exist_ok=True)
    generate().save(target,optimize=True)
    print(target)
