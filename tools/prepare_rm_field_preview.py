"""Offline STEP -> shaded field preview; never a runtime CAD dependency.

Run in an isolated tooling environment with cadquery-ocp and vtk installed.
The input is read-only. No game install, network, or robot interface is used.
This is a baked view of the supplied model, not an interactive CAD editor.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time
import struct


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def outline_mesh(gpu, right, vertical, scale):
    """Retain CAD crease/boundary edges, not the tessellation's diagonals.

    A translucent survey mesh keeps the original Watch grid visible. These
    are geometric RM content additions, not changes to the source material.
    """
    import numpy as np
    face = gpu[:, :, :3].astype(np.float64)
    normal = np.cross(face[:, 1] - face[:, 0], face[:, 2] - face[:, 0])
    normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-12)
    _, inverse = np.unique(np.round(face.reshape(-1, 3), 2), axis=0, return_inverse=True)
    ids = inverse.reshape(-1, 3)
    edges = np.concatenate([np.column_stack((ids[:, a], ids[:, b])) for a, b in ((0, 1), (1, 2), (2, 0))])
    endpoints = np.concatenate([face[:, [a, b]] for a, b in ((0, 1), (1, 2), (2, 0))])
    normals = np.tile(normal, (3, 1))
    edges.sort(axis=1)
    order = np.lexsort((edges[:, 1], edges[:, 0]))
    edges = edges[order]
    first = np.r_[True, np.any(edges[1:] != edges[:-1], axis=1)]
    last = np.r_[np.any(edges[1:] != edges[:-1], axis=1), True]
    # Boundary edges or a change in face normal; opposite coplanar winding
    # still describes one plane and must not reveal triangle diagonals.
    pair_normal = np.abs(np.sum(normals[order] * normals[np.roll(order, -1)], axis=1))
    keep = first & (last | (pair_normal < .97))
    endpoints = endpoints[order[keep]]
    length = np.linalg.norm(endpoints[:, 1] - endpoints[:, 0], axis=1)
    valid = np.flatnonzero(length * scale > .7)
    limit = min(20000, max(0, (120000 - len(gpu)) // 2))
    if len(valid) > limit:
        valid = valid[np.argpartition(length[valid], -limit)[-limit:]]
    endpoints = endpoints[valid]
    delta = endpoints[:, 1] - endpoints[:, 0]
    dx, dy = delta @ right, delta @ vertical
    denominator = np.maximum(np.hypot(dx, dy), 1e-9)
    perpendicular = ((-dy / denominator)[:, None] * right + (dx / denominator)[:, None] * vertical) * (.30 / scale)
    a, b = endpoints[:, 0], endpoints[:, 1]
    quads = np.stack((a-perpendicular, a+perpendicular, b+perpendicular,
                      a-perpendicular, b+perpendicular, b-perpendicular), axis=1).reshape(-1, 3, 3)
    lines = np.zeros((len(quads), 3, 9), dtype='<f4')
    lines[:, :, :3] = quads
    lines[:, :, 5:9] = (.75, .65, .20, .88)
    gpu[:, :, 8] = .17
    return np.concatenate((gpu, lines))


def prepare(source: Path, out: Path, mode: str, size: int = 2048, up: str = "auto") -> dict:
    import numpy as np
    from OCP.STEPControl import STEPControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopoDS import TopoDS
    from OCP.BRep import BRep_Tool
    from OCP.TopLoc import TopLoc_Location
    import vtk
    from vtk.util.numpy_support import numpy_to_vtk

    started = time.perf_counter()
    reader = STEPControl_Reader()
    if reader.ReadFile(str(source)) != IFSelect_RetDone:
        raise ValueError("STEP reader rejected source")
    reader.TransferRoots()
    shape = reader.OneShape()
    if shape.IsNull():
        raise ValueError("STEP contains no transferable shape")
    # Millimetre-space tolerance. Keep this work out of the UI process.
    BRepMesh_IncrementalMesh(shape, 8.0, False, 0.45, True).Perform()
    vertices, faces = [], []
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face(explorer.Current())
        location = TopLoc_Location()
        mesh = BRep_Tool.Triangulation_s(face, location)
        if mesh is not None:
            transform, offset = location.Transformation(), len(vertices)
            for n in range(1, mesh.NbNodes() + 1):
                p = mesh.Node(n).Transformed(transform)
                vertices.append((p.X(), p.Y(), p.Z()))
            reverse = face.Orientation() == TopAbs_REVERSED
            for n in range(1, mesh.NbTriangles() + 1):
                a, b, c = mesh.Triangle(n).Get()
                if reverse:
                    b, c = c, b
                faces.append((a - 1 + offset, b - 1 + offset, c - 1 + offset))
        explorer.Next()
    points = np.asarray(vertices, dtype=np.float32)
    triangles = np.asarray(faces, dtype=np.int64)
    if not len(triangles) or not np.isfinite(points).all():
        raise ValueError("Invalid/empty model tessellation")
    vtk_points = vtk.vtkPoints()
    vtk_points.SetData(numpy_to_vtk(points, deep=True))
    cells = vtk.vtkCellArray()
    cells.SetData(numpy_to_vtk(np.arange(0, len(triangles) * 3 + 1, 3, dtype=np.int64), deep=True),
                  numpy_to_vtk(triangles.ravel(), deep=True))
    data = vtk.vtkPolyData()
    data.SetPoints(vtk_points)
    data.SetPolys(cells)
    normals = vtk.vtkPolyDataNormals()
    normals.SetInputData(data)
    normals.SetFeatureAngle(50)
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputConnection(normals.GetOutputPort())
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetColor(0.78, 0.73, 0.34)
    actor.GetProperty().SetAmbient(0.38)
    actor.GetProperty().SetDiffuse(0.62)
    actor.GetProperty().SetSpecular(0.08)
    renderer = vtk.vtkRenderer()
    renderer.SetBackground(0.10, 0.11, 0.11)
    renderer.SetBackgroundAlpha(0)
    renderer.AddActor(actor)
    bounds = points.min(axis=0), points.max(axis=0)
    center = (bounds[0] + bounds[1]) * 0.5
    extent = bounds[1] - bounds[0]
    radius = float(max(extent))
    # STEP packages do not all use the same up axis (the RMUL files use Y).
    # Camera changes only; source assembly coordinates stay untouched.
    axis = int(np.argmin(extent)) if up == "auto" else "xyz".index(up[-1])
    direction = -1 if up.startswith("-") else 1
    offset = np.array([.75, -1.3, .9])
    view_up = [0, 0, 1]
    if axis == 1:
        offset = np.array([.75, direction * .9, 1.3])
        view_up = [0, direction, 0]
    elif axis == 0:
        offset = np.array([direction * .9, -1.3, .75])
        view_up = [direction, 0, 0]
    camera = renderer.GetActiveCamera()
    camera.ParallelProjectionOn()
    camera.SetFocalPoint(*center)
    camera.SetPosition(*(center + offset * radius))
    camera.SetViewUp(*view_up)
    renderer.ResetCamera()
    direction_vector = -offset / np.linalg.norm(offset)
    right = np.cross(direction_vector, view_up)
    right /= np.linalg.norm(right)
    vertical = np.cross(right, direction_vector)
    projected = np.column_stack(((points - center) @ right, (points - center) @ vertical))
    # Fit the *circular* Watch viewport, not just an axis-aligned square; no
    # bases or field corners are accidentally cropped out of the overview.
    camera.SetParallelScale(float(np.linalg.norm(projected, axis=1).max()) * 1.08)
    renderer.ResetCameraClippingRange()
    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetAlphaBitPlanes(1)
    window.SetMultiSamples(8)
    window.SetSize(size, size)
    window.AddRenderer(renderer)
    window.Render()
    capture = vtk.vtkWindowToImageFilter()
    capture.SetInput(window)
    capture.SetInputBufferTypeToRGBA()
    capture.ReadFrontBufferOff()
    capture.Update()
    out.mkdir(parents=True, exist_ok=True)
    preview = out / f"{mode}.png"
    writer = vtk.vtkPNGWriter()
    writer.SetFileName(str(preview))
    writer.SetInputConnection(capture.GetOutputPort())
    writer.Write()
    window.Finalize()
    # Retained GPU mesh: genuine STEP geometry, not a screenshot texture. An
    # offline reduction bounds the 2.9M-triangle RMUC model before UI loading.
    decimator = vtk.vtkQuadricDecimation()
    weld = vtk.vtkCleanPolyData()
    weld.SetInputData(data)
    weld.ToleranceIsAbsoluteOn()
    weld.SetAbsoluteTolerance(.05)
    weld.Update()
    decimator.SetInputConnection(weld.GetOutputPort())
    decimator.SetTargetReduction(max(0.0, 1 - 80000 / len(triangles)))
    decimator.Update()
    reduced = decimator.GetOutput()
    from vtk.util.numpy_support import vtk_to_numpy
    mesh_points = vtk_to_numpy(reduced.GetPoints().GetData()).astype(np.float64)
    connectivity = vtk_to_numpy(reduced.GetPolys().GetConnectivityArray()).reshape(-1, 3)
    if len(connectivity) > 100000:
        # CAD has millions of disconnected submillimetre fixtures which no
        # topology-preserving decimator can collapse. Retain the largest
        # authored triangles as the overview LOD; never load an unbounded mesh.
        candidate = mesh_points[connectivity]
        areas = np.linalg.norm(np.cross(candidate[:, 1] - candidate[:, 0], candidate[:, 2] - candidate[:, 0]), axis=1)
        connectivity = connectivity[np.argpartition(areas, -100000)[-100000:]]
    # This is the same authored isometric view as the overview. Keep XYZ in
    # the payload and project it in the vertex shader via a source-plane matrix.
    face = mesh_points[connectivity]
    normal = np.cross(face[:, 1] - face[:, 0], face[:, 2] - face[:, 0])
    normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-12)
    view_depth = ((face.mean(axis=1) - center) @ direction_vector)
    order = np.argsort(view_depth)[::-1]
    face = face[order]
    light = offset / np.linalg.norm(offset)
    intensity = .38 + .62 * np.abs(normal[order] @ light)
    color = intensity[:, None] * np.array([.78, .73, .34])
    color = np.where(color <= .04045, color / 12.92, ((color + .055) / 1.055) ** 2.4)
    gpu = np.zeros((len(face), 3, 9), dtype='<f4')
    gpu[:, :, :3] = face
    gpu[:, :, 5:8] = color[:, None, :]
    gpu[:, :, 8] = 1
    # The field floats *inside* the source central platform. Preserve a clear
    # ring/glyph margin instead of stretching a rectangular board to its rim.
    scale = 172 / float(np.linalg.norm(projected, axis=1).max())
    gpu = outline_mesh(gpu, right, vertical, scale)
    matrix = np.eye(4)
    matrix[0, :3] = right * scale
    matrix[1, :3] = -vertical * scale
    matrix[2, :3] = direction_vector * scale
    matrix[:2, 3] = [220 - center @ right * scale, 228 + center @ vertical * scale]
    mesh_file = out / f'{mode}.efmesh'
    with mesh_file.open('wb') as stream:
        stream.write(b'PRMESH01')
        stream.write(struct.pack('<II', len(gpu) * 3, len(gpu) * 3))
        stream.write(matrix.astype('<f8').tobytes(order='F'))
        stream.write(gpu.tobytes())
        stream.write(np.arange(len(gpu) * 3, dtype='<u4').tobytes())
    record = {"schema": 1, "mode": mode, "season": 2027,
              "source_file": source.name, "source_sha256": digest(source),
              "preview_sha256": digest(preview), "preview": preview.name,
              "vertices": len(vertices), "triangles": len(triangles),
              "bounds_mm": [b.tolist() for b in bounds], "size": size,
              "camera_up_axis": up, "detected_vertical_axis": axis,
              "gpu_mesh": mesh_file.name, "gpu_mesh_sha256": digest(mesh_file),
              "gpu_triangles": len(gpu),
              "gpu_surface_triangles": len(face),
              "presentation": "original STEP overview: PNG reference and retained GPU triangle mesh; offline LOD, no live CAD",
              "build_seconds": round(time.perf_counter() - started, 2)}
    (out / f"{mode}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--mode", choices=("RMUC7v7", "RMUL3v3", "RMUL1v1"), required=True)
    parser.add_argument("--size", type=int, choices=(1024, 2048, 4096), default=2048)
    parser.add_argument("--up", choices=("auto", "x", "y", "z", "-y"), default="auto")
    args = parser.parse_args()
    print(json.dumps(prepare(args.source.resolve(), args.out.resolve(), args.mode, args.size, args.up), indent=2))
