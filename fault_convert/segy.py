"""npy cube (inline, xline, time) -> SEG-Y that Petrel imports with byte 189/193 lines, 181/185 coords.

Petrel import settings: 3D; X coordinate 181, Y coordinate 185; line detection "Trace header
fields", inline 189, crossline 193. Coordinates are synthetic (line * bin_m), not survey geometry.
"""
from pathlib import Path

import numpy as np
import segyio

from .grid import Grid


def non_ascii_paths(paths):
    """Output SEG-Y paths containing non-ASCII characters (e.g. Chinese); Petrel fails to read those."""
    return [str(Path(p).resolve()) for p in paths if not str(Path(p).resolve()).isascii()]


def write_segy(cube, out_path, grid, title="Fault_convert_tools", log=print):
    ni, nx, nt = cube.shape
    o, dt, b = grid.origin, grid.dt_ms, grid.bin_m
    spec = segyio.spec()
    spec.format = 5  # IEEE float32
    spec.sorting = segyio.TraceSortingFormat.INLINE_SORTING
    spec.ilines = np.arange(o[0], o[0] + ni, dtype=np.int32)
    spec.xlines = np.arange(o[1], o[1] + nx, dtype=np.int32)
    spec.samples = o[2] * dt + np.arange(nt) * dt
    t0 = int(round(o[2] * dt))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if non_ascii_paths([out_path]):
        log(f"警告：SEG-Y 路径含中文或其他非 ASCII 字符，Petrel 导入会出错：{out_path.resolve()}")
    with segyio.create(str(out_path), spec) as f:
        tr = 0
        for i in range(ni):
            il = int(o[0] + i)
            block = np.ascontiguousarray(cube[i], dtype=np.float32)
            for x in range(nx):
                xl = int(o[1] + x)
                f.header[tr] = {
                    segyio.TraceField.TRACE_SEQUENCE_LINE: tr + 1,
                    segyio.TraceField.INLINE_3D: il,
                    segyio.TraceField.CROSSLINE_3D: xl,
                    segyio.TraceField.CDP: tr + 1,
                    segyio.TraceField.CDP_X: int(round(xl * b * 100)),
                    segyio.TraceField.CDP_Y: int(round(il * b * 100)),
                    segyio.TraceField.SourceGroupScalar: -100,
                    segyio.TraceField.TRACE_SAMPLE_COUNT: nt,
                    segyio.TraceField.TRACE_SAMPLE_INTERVAL: int(round(dt * 1000)),
                    segyio.TraceField.DelayRecordingTime: t0,
                }
                f.trace[tr] = block[x]
                tr += 1
            if (i + 1) % 50 == 0 or i + 1 == ni:
                log(f"segy inline {i + 1}/{ni}")
        f.bin.update(hdt=int(round(dt * 1000)), hns=nt, format=5)
        f.text[0] = segyio.tools.create_text_header({
            1: f"{title} -> SEG-Y for Petrel",
            2: f"SOURCE {out_path.stem[:50]}  SHAPE I/X/T {ni}x{nx}x{nt}",
            3: f"INLINE BYTE 189 = global inline {o[0]}..{o[0] + ni - 1}",
            4: f"XLINE  BYTE 193 = global xline  {o[1]}..{o[1] + nx - 1}",
            5: f"CDP_X BYTE 181 = XL*{b:g}  CDP_Y BYTE 185 = IL*{b:g} (scalar -100)",
            6: f"DT {dt:g} MS  FIRST SAMPLE {t0} MS (global sample {o[2]})",
            7: "COORDINATES ARE SYNTHETIC - NOT REAL SURVEY GEOMETRY",
        })
    log(f"wrote {out_path}")
    return str(out_path)


def npy_to_segy(npy_path, out_path, grid, log=print):
    cube = np.load(npy_path, mmap_mode="r")
    if cube.ndim != 3:
        raise ValueError("cube must be 3-D (inline, xline, time)")
    if not isinstance(grid, Grid):
        grid = Grid(*grid)
    return write_segy(cube, out_path, grid, title=Path(npy_path).stem[:30], log=log)


def check_segy(path, npy_path=None):
    """Read a written SEG-Y back: geometry and, optionally, equality with the source npy."""
    with segyio.open(str(path)) as f:
        info = {"inline": [int(f.ilines[0]), int(f.ilines[-1])], "xline": [int(f.xlines[0]), int(f.xlines[-1])],
                "time_ms": [float(f.samples[0]), float(f.samples[-1])],
                "shape": [len(f.ilines), len(f.xlines), len(f.samples)]}
        if npy_path is not None:
            info["equal_to_npy"] = bool(np.array_equal(segyio.tools.cube(f), np.load(npy_path, mmap_mode="r")))
    return info
