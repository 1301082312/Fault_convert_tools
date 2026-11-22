"""Petrel fault surfaces (GOCAD TSurf .ts) -> binary / instance fault label cubes on a seismic grid.

Coordinates follow the SEG-Y convention of segy.py: inline = Y / bin_m, xline = X / bin_m,
sample = T(ms) / dt_ms (T in the file is in seconds when AXIS_UNIT says "s"). Each surface becomes
xline(inline, sample) by rasterizing its triangles in the (inline, sample) plane; every
(inline, sample) cell is then marked across xline from halfway toward its inline/sample neighbours,
at least 2 traces wide. This is the rule used for the R0004 / R0008 / R0009 / gap training labels,
so the outputs match those files voxel for voxel.

Instance labels: each .ts file gets its own id (1, 2, ... in natural file-name order, or from
`start_id`). Where two faults touch, the voxel keeps the id written first; such voxels are counted
per fault in the report. Binary = instance > 0.
"""
import glob
import re
from pathlib import Path

import numpy as np

MAX_IL_JUMP = 12.0  # traces: larger xline jumps between adjacent inlines are not bridged
MAX_T_JUMP = 3.0    # traces per sample: larger is a hook at a surface edge, not bridged


def natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(s))]


def read_tsurf(path):
    """Return (vertices Nx3 [X, Y, T_ms], triangles Mx3, name)."""
    verts, tris, name, z_unit = {}, [], Path(path).stem, None
    for line in open(path, encoding="utf-8", errors="replace"):
        p = line.split()
        if not p:
            continue
        if p[0] in ("VRTX", "PVRTX"):
            verts[int(p[1])] = (float(p[2]), float(p[3]), float(p[4]))
        elif p[0] == "TRGL":
            tris.append([int(v) for v in p[1:4]])
        elif p[0].startswith("name:"):
            name = line.split(":", 1)[1].strip() or name
        elif p[0] == "AXIS_UNIT" and len(p) >= 4:
            z_unit = p[3].strip('"').lower()
    if not verts or not tris:
        return np.zeros((0, 3)), np.zeros((0, 3), int), name
    ids = sorted(verts)
    index = {k: n for n, k in enumerate(ids)}
    v = np.array([verts[k] for k in ids], dtype=np.float64)
    if z_unit in ("s", "sec", "second", "seconds") or (z_unit is None and np.abs(v[:, 2]).max() < 20):
        v[:, 2] *= 1000.0  # seconds -> ms
    v[:, 2] = np.abs(v[:, 2])  # Petrel writes TWT as negative elevation in some exports
    t = np.array([[index[i] for i in tri] for tri in tris if all(i in index for i in tri)], dtype=int)
    return v, t, name


def surface(verts, tris, grid, shape):
    """xline (local, float) on the (inline, sample) grid of the cube; NaN where absent."""
    ni, _, nt = shape
    o, b, dt = grid.origin, grid.bin_m, grid.dt_ms
    il = verts[:, 1] / b - o[0]
    xl = verts[:, 0] / b - o[1]
    t = verts[:, 2] / dt - o[2]
    surf = np.full((ni, nt), np.nan)
    for a, bb, c in tris:
        P = np.array([[il[a], t[a]], [il[bb], t[bb]], [il[c], t[c]]])
        T = np.array([P[1] - P[0], P[2] - P[0]]).T
        if abs(np.linalg.det(T)) < 1e-9:
            continue
        i0, i1 = max(int(np.ceil(P[:, 0].min())), 0), min(int(np.floor(P[:, 0].max())), ni - 1)
        t0, t1 = max(int(np.ceil(P[:, 1].min())), 0), min(int(np.floor(P[:, 1].max())), nt - 1)
        if i0 > i1 or t0 > t1:
            continue
        I, Tt = np.meshgrid(np.arange(i0, i1 + 1), np.arange(t0, t1 + 1), indexing="ij")
        u, v = np.linalg.solve(T, np.stack([I.ravel() - P[0, 0], Tt.ravel() - P[0, 1]]))
        inside = (u >= -1e-6) & (v >= -1e-6) & (u + v <= 1 + 1e-6)
        x = xl[a] + u * (xl[bb] - xl[a]) + v * (xl[c] - xl[a])
        ii, tt = I.ravel()[inside], Tt.ravel()[inside]
        cur = surf[ii, tt]
        surf[ii, tt] = np.where(np.isnan(cur), x[inside], cur)
    return surf


def rasterize(surf, nx):
    """Boolean mask (ni, nx, nt) of the fault: each (il, t) cell spans xline from halfway toward
    its inline/sample neighbours, >= 2 traces wide; parts outside the cube are dropped."""
    ni, nt = surf.shape
    lo, hi = surf.copy(), surf.copy()
    for axis in (0, 1):
        for shift in (1, -1):
            nb = np.roll(surf, shift, axis=axis)
            edge = [slice(None)] * 2
            edge[axis] = 0 if shift == 1 else -1
            nb[tuple(edge)] = np.nan
            nb[np.abs(nb - surf) > (MAX_IL_JUMP if axis == 0 else MAX_T_JUMP)] = np.nan
            mid = (surf + nb) / 2
            lo = np.fmin(lo, mid)
            hi = np.fmax(hi, mid)
    mask = np.zeros((ni, nx, nt), bool)
    i_idx, t_idx = np.nonzero((surf >= 0) & (surf <= nx - 1))
    a = np.floor(lo[i_idx, t_idx]).astype(int)
    b = np.maximum(np.floor(hi[i_idx, t_idx]).astype(int) + 1, a + 1)
    for i, t, x0, x1 in zip(i_idx, t_idx, a, b):
        x0, x1 = max(x0, 0), min(x1, nx - 1)
        if x0 <= x1:
            mask[i, x0:x1 + 1, t] = True
    return mask


def list_ts(source):
    """A folder (all *.ts, natural order) or an explicit list of files."""
    if isinstance(source, (str, Path)) and Path(source).is_dir():
        return sorted(glob.glob(str(Path(source) / "*.ts")), key=natural_key)
    if isinstance(source, (str, Path)):
        return [str(source)]
    return [str(s) for s in source]


def build_labels(ts_source, grid, shape, start_id=1, inline_range=None, log=print):
    """Return (instance uint16 cube, report list). inline_range=(a, b) keeps only those global inlines."""
    shape = tuple(int(v) for v in shape)
    files = list_ts(ts_source)
    if not files:
        raise ValueError(f"no .ts files in {ts_source}")
    inst = np.zeros(shape, np.uint16)
    keep = None
    if inline_range is not None:
        keep = (max(inline_range[0] - grid.origin[0], 0), min(inline_range[1] - grid.origin[0], shape[0] - 1))
    report = []
    for n, f in enumerate(files):
        fid = start_id + n
        if fid > np.iinfo(np.uint16).max:
            raise ValueError("more than 65535 faults")
        verts, tris, name = read_tsurf(f)
        entry = {"id": fid, "file": Path(f).name, "name": name, "vertices": len(verts),
                 "triangles": len(tris), "voxels": 0, "overlap_voxels": 0}
        if len(tris):
            m = rasterize(surface(verts, tris, grid, shape), shape[1])
            if keep is not None:
                m[:keep[0]] = False
                m[keep[1] + 1:] = False
            free = m & (inst == 0)
            inst[free] = fid
            entry["voxels"], entry["overlap_voxels"] = int(m.sum()), int((m & ~free).sum())
        report.append(entry)
        log(f"[{n + 1}/{len(files)}] id {fid} {Path(f).name} ({name}): {entry['voxels']} voxels"
            + ("  (outside cube)" if len(tris) and entry["voxels"] == 0 else "")
            + ("  (empty file)" if not len(tris) else ""))
    return inst, report
