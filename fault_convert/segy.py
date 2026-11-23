"""npy cube (inline, xline, time) -> SEG-Y that Petrel imports with byte 189/193 lines, 181/185 coords.

Petrel import settings: 3D; X coordinate 181, Y coordinate 185; line detection "Trace header
fields", inline 189, crossline 193. The same values are also written where Petrel's plain
"SEG-Y seismic data" import looks by default (inline 5; xline 17 and 21; X/Y 73/77), so that
import works too. Coordinates are synthetic (line * bin_m), not survey geometry.
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
                    segyio.TraceField.TRACE_SEQUENCE_FILE: il,   # byte 5: Petrel default line number
                    segyio.TraceField.EnergySourcePoint: xl,     # byte 17: Petrel default shot point
                    segyio.TraceField.CDP: xl,                   # byte 21: Petrel default CDP / trace number
                    segyio.TraceField.CDP_X: int(round(xl * b * 100)),
                    segyio.TraceField.CDP_Y: int(round(il * b * 100)),
                    segyio.TraceField.SourceX: int(round(xl * b * 100)),  # bytes 73/77: Petrel default X/Y
                    segyio.TraceField.SourceY: int(round(il * b * 100)),
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
            8: "ALSO: BYTE 5 = INLINE, 17 AND 21 = XLINE, 73/77 = X/Y (PETREL DEFAULTS)",
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


def add_petrel_default_bytes(path, log=print):
    """Patch an existing SEG-Y written by this tool (189/193 lines, 181/185 coords) in place:
    copy inline -> byte 5, xline -> bytes 17 and 21, CDP X/Y -> bytes 73/77. Samples are untouched."""
    from .segy_read import read_binary, SAMPLE_BYTES
    info = read_binary(path)
    trace_bytes = 240 + info["ns"] * SAMPLE_BYTES[info["format"]]
    offset = 3600 + 3200 * info["ext_headers"]
    raw = np.memmap(path, dtype=np.uint8, mode="r+", offset=offset)
    n = raw.size // trace_bytes
    heads = raw[:n * trace_bytes].reshape(n, trace_bytes)

    def get(byte):
        return heads[:, byte - 1:byte + 3].copy().view(">i4").ravel()

    def put(byte, values):
        heads[:, byte - 1:byte + 3] = np.ascontiguousarray(values.astype(">i4")).view(np.uint8).reshape(n, 4)

    il, xl, x, y = get(189), get(193), get(181), get(185)
    if not (np.ptp(il) or np.ptp(xl)):
        raise ValueError("bytes 189/193 hold no line numbers; not a SEG-Y written by this tool")
    put(5, il), put(17, xl), put(21, xl), put(73, x), put(77, y)
    raw.flush()
    del heads, raw
    log(f"patched {n} trace headers of {path}: 5=inline, 17/21=xline, 73/77=X/Y")
    return n
