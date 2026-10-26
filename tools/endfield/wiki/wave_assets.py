"""把本体地面网格、UV和噪声位移投影为小型循环帧，客户端只负责播放。"""
from array import array
import hashlib
import struct
from tools.endfield.prepare_boot import decode


def prepare_waves(root, rows, output, images, provenance):
    from PIL import Image,ImageChops
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QGuiApplication, QImage, QOffscreenSurface, QOpenGLContext, QSurfaceFormat
    from PySide6.QtOpenGL import (QOpenGLBuffer, QOpenGLFramebufferObject, QOpenGLShader,
                                 QOpenGLShaderProgram, QOpenGLTexture, QOpenGLVertexArrayObject)
    by_id = {r["path_id"]:r for r in rows if "path_id" in r}
    mesh_row = by_id[374149229920228294]
    mesh = decode(root,mesh_row)
    count = mesh["m_VertexData"]["m_VertexCount"]
    resource = root/"_resources"/"Bundle"/mesh_row["source_path"]/mesh["m_StreamData"]["path"].split("/")[-1]
    stream = resource.read_bytes()
    offset = mesh["m_StreamData"]["offset"]
    assert mesh["m_StreamData"]["size"]==count*32,"Wiki ground vertex layout changed"
    indices = struct.unpack("<"+str(len(mesh["m_IndexBuffer"])//2)+"H",bytes(mesh["m_IndexBuffer"]))
    vertices = array("f")
    for i in indices:
        vertices.extend(struct.unpack_from("<2f",stream,offset+i*16))
        vertices.extend(struct.unpack_from("<4f",stream,offset+count*16+i*16))
    material_row = by_id[-5611585278553019446]
    props = decode(root,material_row)["m_SavedProperties"]
    floats,colors = dict(props["m_Floats"]),dict(props["m_Colors"])
    camera_row = by_id[8843913985749677385]
    camera = decode(root,camera_row)
    # 先保留实际Main相机的镜头、位置和piece_01旋转后的地面朝向。
    camera_transform = decode(root,by_id[-7729338905824266935])
    position = camera_transform["m_LocalPosition"]
    instance_rows = [r for r in rows if str(r.get("parent_asset_path","")).endswith("/wikimodelshow.prefab")
                     and r["type"]=="GameObject"]
    piece_go = next(d for r in instance_rows if (d:=decode(root,r)).get("m_Name")=="piece_01")
    piece_row = by_id[piece_go["m_Component"][0]["component"]["m_PathID"]]
    piece = decode(root,piece_row)
    parent = decode(root,by_id[piece["m_Father"]["m_PathID"]])
    parent_scale = parent["m_LocalScale"]["x"]
    q = piece["m_LocalRotation"];x,y,z,w = (q[k] for k in "xyzw")
    # 实际实例覆盖了独立prefab：y=-1.6、scale=(2,2,1)且朝向不同，不能丢掉覆盖值。
    axes = ((1-2*y*y-2*z*z,2*x*y+2*z*w,2*x*z-2*y*w),
            (2*x*y-2*z*w,1-2*x*x-2*z*z,2*y*z+2*x*w),
            (2*x*z+2*y*w,2*y*z-2*x*w,1-2*x*x-2*y*y))
    basis = [tuple(v*piece["m_LocalScale"][axis]*parent_scale for v in vector) for axis,vector in zip("xyz",axes)]
    app = QGuiApplication.instance() or QGuiApplication([])
    fmt = QSurfaceFormat();fmt.setVersion(3,3);fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    surface = QOffscreenSurface();surface.setFormat(fmt);surface.create()
    context = QOpenGLContext();context.setFormat(fmt)
    if not context.create() or not context.makeCurrent(surface):
        raise RuntimeError("Wiki wave projection requires a desktop OpenGL context")
    functions = context.functions()
    program = QOpenGLShaderProgram()
    vertex = """#version 330
        layout(location=0) in vec2 point; layout(location=1) in vec4 texcoords;
        uniform sampler2D noiseTex; uniform float time, intensity, offsetZ, fov;
        uniform vec2 noiseScale, noiseSpeed; uniform vec3 camera;
        uniform float lensShift; uniform vec3 meshX,meshY,meshZ,meshPosition;
        out vec2 mainUV, maskUV;
        void main() {
            float noise=textureLod(noiseTex,texcoords.zw*noiseScale+noiseSpeed*time,0).r;
            vec3 world=meshPosition+point.x*meshX+point.y*meshY+noise*intensity*offsetZ*meshZ;
            float depth=camera.z-world.z;
            float f=1.0/tan(radians(fov)*.5);
            gl_Position=vec4(-world.x*f/(16.0/9.0)-2.0*lensShift*depth,
                (world.y-camera.y)*f,depth*1.001-0.2,depth);
            mainUV=texcoords.xy; maskUV=texcoords.zw;
        }"""
    fragment = """#version 330
        uniform sampler2D mainTex,maskTex; uniform float time, mainSpeed, tintAlpha;
        in vec2 mainUV,maskUV; out vec4 color;
        void main() {
            float a=clamp(texture(mainTex,mainUV+vec2(mainSpeed*time,0)).r*
                texture(maskTex,maskUV).r*tintAlpha,0,1);
            color=vec4(vec3(a),a);
        }"""
    for kind,source in ((QOpenGLShader.ShaderTypeBit.Vertex,vertex),(QOpenGLShader.ShaderTypeBit.Fragment,fragment)):
        if not program.addShaderFromSourceCode(kind,source):raise RuntimeError(program.log())
    if not program.link():raise RuntimeError(program.log())
    vao = QOpenGLVertexArrayObject();vao.create();vao.bind()
    vbo = QOpenGLBuffer();vbo.create();vbo.bind();vbo.allocate(vertices.tobytes(),len(vertices)*4)
    program.bind()
    def uniform(name,value):
        functions.glUniform1f(program.uniformLocation(name),float(value))
    for index,size,at in ((0,2,0),(1,4,8)):
        program.enableAttributeArray(index);program.setAttributeBuffer(index,0x1406,at,size,24)
    textures = []
    texture_rows = []
    envs = dict(props["m_TexEnvs"])
    for unit,(field,sampler) in enumerate((("_MainTex","mainTex"),("_MaskTex","maskTex"),("_OffsetTex","noiseTex"))):
        row = by_id[envs[field]["m_Texture"]["m_PathID"]];texture_rows.append(row)
        tex = QOpenGLTexture(QImage(str(root/row["output_path"])).mirrored())
        tex.setWrapMode(QOpenGLTexture.WrapMode.Repeat)
        tex.setMinMagFilters(QOpenGLTexture.Filter.Linear,QOpenGLTexture.Filter.Linear)
        tex.bind(unit);textures.append(tex);functions.glUniform1i(program.uniformLocation(sampler),unit)
    uniforms = {"intensity":floats["_OffsetIntensity"],"offsetZ":colors["_OffsetDir"]["b"],
                "fov":camera["m_Lens"]["FieldOfView"],"lensShift":camera["m_Lens"]["LensShift"]["x"],
                "mainSpeed":colors["_MainTexUVSpeed"]["r"],"tintAlpha":floats["_TintColorAlpha"]}
    for key,value in uniforms.items():uniform(key,float(value))
    functions.glUniform3f(program.uniformLocation("camera"),*(position[k] for k in "xyz"))
    for name,vector in zip(("meshX","meshY","meshZ"),basis):
        functions.glUniform3f(program.uniformLocation(name),*vector)
    functions.glUniform3f(program.uniformLocation("meshPosition"),*(piece["m_LocalPosition"][k]*parent_scale for k in "xyz"))
    functions.glUniform2f(program.uniformLocation("noiseScale"),envs["_OffsetTex"]["m_Scale"]["x"],envs["_OffsetTex"]["m_Scale"]["y"])
    functions.glUniform2f(program.uniformLocation("noiseSpeed"),colors["_OffsetSpeed"]["r"],colors["_OffsetSpeed"]["g"])
    fbo = QOpenGLFramebufferObject(QSize(640,360))
    if not fbo.isValid():raise RuntimeError("Wiki ground projection framebuffer failed")
    directory = output/"waves";directory.mkdir(exist_ok=True)
    dependencies = [{"source":r["parent_asset_path"],"bundle":r["source_path"],"object":r["path_id"]}
                    for r in (material_row,camera_row,mesh_row,piece_row,*texture_rows)]
    frames = []
    try:
        for index in range(80):
            fbo.bind();functions.glViewport(0,0,640,360)
            program.bind();vao.bind()
            for unit,tex in enumerate(textures):tex.bind(unit)
            functions.glDisable(0x0B44);functions.glDisable(0x0B71);functions.glDisable(0x0BD0)
            functions.glEnable(0x0BE2);functions.glBlendFunc(1,0x0303)
            # 先合成到终端底色；运行时可精确混合相邻帧，避免透明帧交叠导致明暗脉动。
            functions.glClearColor(230/255,229/255,227/255,1);functions.glClear(0x4000)
            uniform("time",float(index/8))
            functions.glDrawArrays(0x0004,0,len(indices))
            error = functions.glGetError()
            if error:raise RuntimeError(f"Wiki ground projection GL error: {error}")
            path = directory/f"{index:03}.png"
            projected = fbo.toImage().copy(0,180,640,180).convertToFormat(QImage.Format.Format_RGBA8888)
            raster = Image.frombytes("RGBA",(640,180),bytes(projected.constBits()))
            # 原场景的光照/后处理不进入Qt，波面亮度转成底部淡灰装饰，中心内容区逐渐隐去。
            shade = raster.getchannel("R").point(lambda value:max(0,min(22,round((value-230)*22/25))))
            fade = Image.new("L",(640,180))
            # 保留更多原波面，以平滑过渡融入底色，不能暴露网格远端的硬切边。
            weights = [max(0,min(1,(y-45)/80)) for y in range(180)]
            fade.putdata([round(255*t*t*(3-2*t)) for t in weights for _ in range(640)])
            shade = ImageChops.multiply(shade,fade)
            channels = [ImageChops.subtract(Image.new("L",(640,180),value),shade) for value in (230,229,227)]
            Image.merge("RGBA",(*channels,Image.new("L",(640,180),255))).save(path)
            key = f"wave_{index:03}";frames.append(key);images[key] = "waves/"+path.name
            provenance.append({"output":images[key],"source":mesh_row["parent_asset_path"],
                "texture_name":"Wiki ground projection", "bundle":mesh_row["source_path"],"object":mesh_row["path_id"],
                "sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"dependencies":dependencies if index==0 else [],
                "adaptation":"source mesh/UVs, actual instance transform, Main camera and noise displacement; bottom grey projection"})
    finally:
        fbo.release();program.release();vbo.destroy();vao.destroy()
        for tex in textures:tex.destroy()
        context.doneCurrent()
    if len({entry["sha256"] for entry in provenance[-80:]})<2:
        raise RuntimeError("Wiki ground projection did not animate")
    return {"frames":frames,"fps":8,"period":10,"rect":[0,540,1920,540],
            "source_uniforms":uniforms,"camera_position":position,"instance_transform":piece,"parent_scale":parent_scale,
            "qt_tone_adaptation":{"max_grey_depth":22,"fade_start":45,"fade_span":80,"fade_curve":"smoothstep"}}
