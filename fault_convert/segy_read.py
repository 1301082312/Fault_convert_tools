"""SEG-Y -> npy cube (inline, xline, time), with the common header byte layouts and auto-detection.

Trace headers are read in one pass through a memory map (fast even for multi-GB files); trace
samples are read with segyio, which handles IBM and IEEE floats. Traces are placed on the
(inline, xline) grid by their header values, so sorting order does not matter and missing traces
are allowed (filled with 0 and reported, optionally saved as a trace mask).
"""
import json
import struct
from pathlib import Path

import numpy as np
import segyio

# (inline byte, xline byte, description) — tried in this order by auto-detection
LINE_PRESETS = [
    (189, 193, "SEG-Y rev1 标准 INLINE_3D / CROSSLINE_3D"),
    (9, 21, "FFID / CDP"),
    (221, 21, "221 / CDP（部分处理软件）"),
    (5, 21, "道序号(卷内) / CDP"),
    (9, 13, "FFID / 道号(炮内)"),
    (17, 21, "炮点号 / CDP"),
    (213, 21, "213 / CDP"),
    (1, 5, "道序号 / 道序号(卷内)"),
]
COORD_PRESETS = [(181, 185, "CDP X / Y"), (73, 77, "炮点 X / Y"), (81, 85, "检波点 X / Y")]
FOUR_BYTE = {1, 5, 9, 13, 17, 21, 25, 37, 41, 45, 49, 53, 57, 61, 65, 73, 77, 81, 85,
             181, 185, 189, 193, 197, 201, 213, 221, 225, 229, 233}
TWO_BYTE = {29, 31, 33, 35, 69, 71, 89, 91, 115, 117, 119, 121, 123, 125, 127, 129, 131,
            133, 135, 137, 139, 141, 143, 145, 147, 149, 151, 153, 155, 157, 159, 161, 163,
            165, 167, 169, 171, 173, 175, 177, 179, 203, 215, 217, 219}
SAMPLE_BYTES = {1: 4, 2: 4, 3: 2, 5: 4, 6: 8, 8: 1, 10: 4, 11: 2, 16: 1}


def read_binary(path):
    with open(path, "rb") as f:
        f.seek(3200)
        b = f.read(400)
    u16 = lambda o: struct.unpack(">H", b[o:o + 2])[0]  # noqa: E731
    fmt, ns, dt_us = u16(24), u16(20), u16(16)
    ext = struct.unpack(">h", b[304:306])[0]
    return {"format": fmt, "ns": ns, "dt_ms": dt_us / 1000.0, "ext_headers": max(ext, 0)}


def read_headers(path):
    """All trace headers as an (n, 240) uint8 array plus binary-header info."""
    info = read_binary(path)
    if info["format"] not in SAMPLE_BYTES:
        raise ValueError(f"unsupported sample format code {info['format']}")
    trace_bytes = 240 + info["ns"] * SAMPLE_BYTES[info["format"]]
    offset = 3600 + 3200 * info["ext_headers"]
    raw = np.memmap(path, dtype=np.uint8, mode="r", offset=offset)
    n = raw.size // trace_bytes
    if n == 0:
        raise ValueError("no traces found")
    heads = np.ascontiguousarray(raw[:n * trace_bytes].reshape(n, trace_bytes)[:, :240])
    del raw
    info["traces"] = n
    return heads, info


def field(heads, byte):
    byte = int(byte)
    if byte in TWO_BYTE:
        return heads[:, byte - 1:byte + 1].copy().view(">i2").ravel().astype(np.int64)
    if byte in FOUR_BYTE or 1 <= byte <= 237:
        return heads[:, byte - 1:byte + 3].copy().view(">i4").ravel().astype(np.int64)
    raise ValueError(f"bad header byte {byte}")


def grid_of(il, xl):
    """Return (ilines, xlines, i_index, x_index, duplicates) for header values."""
    ils, i_idx = np.unique(il, return_inverse=True)
    xls, x_idx = np.unique(xl, return_inverse=True)
    dup = len(il) - len(np.unique(i_idx.astype(np.int64) * len(xls) + x_idx))
    return ils, xls, i_idx, x_idx, int(dup)


def detect_lines(heads):
    """Candidate (inline byte, xline byte) pairs that give a unique 2-D grid, best first."""
    n = len(heads)
    out = []
    for ib, xb, desc in LINE_PRESETS:
        il, xl = field(heads, ib), field(heads, xb)
        ni, nx = len(np.unique(il)), len(np.unique(xl))
        if ni < 2 or nx < 2:
            continue
        ils, xls, _, _, dup = grid_of(il, xl)
        if dup:
            continue
        out.append({"inline_byte": ib, "xline_byte": xb, "desc": desc, "n_il": ni, "n_xl": nx,
                    "filled": n / (ni * nx), "inline": [int(ils[0]), int(ils[-1])],
                    "xline": [int(xls[0]), int(xls[-1])]})
    out.sort(key=lambda c: -c["filled"])  # complete grids first, preset order kept among equals
    return out


def coords(heads, xb, yb, scalar_byte=71):
    x, y = field(heads, xb).astype(np.float64), field(heads, yb).astype(np.float64)
    s = field(heads, scalar_byte)
    f = np.ones(len(s))
    f[s < 0] = 1.0 / np.abs(s[s < 0])
    f[s > 0] = s[s > 0]
    return x * f, y * f


def segy_to_npy(path, out_npy, inline_byte="auto", xline_byte="auto", coord_bytes="auto",
                inline_range=None, origin_mode="lines", fill=0.0, log=print):
    """Write out_npy (float32, inline x xline x time) and <out>_info.json; return the info dict.

    origin_mode 'lines': origin_global_ixt = (first inline number, first xline number, t0/dt), the
    convention of this tool's SEG-Y export (round trip). 'zero': origin = (0, 0, t0/dt).
    """
    path, out_npy = Path(path), Path(out_npy)
    heads, info = read_headers(path)
    log(f"{path.name}: {info['traces']} traces, {info['ns']} samples, dt {info['dt_ms']:g} ms, format {info['format']}")
    cands = detect_lines(heads)
    if inline_byte == "auto" or xline_byte == "auto":
        if not cands:
            raise ValueError("could not find inline/xline bytes automatically; give them explicitly")
        for c in cands[:4]:
            log(f"  候选 inline {c['inline_byte']} / xline {c['xline_byte']} ({c['desc']}): "
                f"{c['n_il']} x {c['n_xl']}, 完整度 {c['filled']:.1%}")
        inline_byte, xline_byte = cands[0]["inline_byte"], cands[0]["xline_byte"]
        log(f"自动选择 inline 字节 {inline_byte}，xline 字节 {xline_byte}")
    il, xl = field(heads, inline_byte), field(heads, xline_byte)
    keep = np.ones(len(il), bool)
    if inline_range is not None:
        keep = (il >= inline_range[0]) & (il <= inline_range[1])
        if not keep.any():
            raise ValueError(f"no traces with inline in {inline_range}")
    ils, xls, i_idx, x_idx, dup = grid_of(il[keep], xl[keep])
    if dup:
        raise ValueError(f"{dup} traces share an (inline, xline) pair with bytes {inline_byte}/{xline_byte}; "
                         "wrong bytes or a 2-D / prestack file")
    trace_ids = np.nonzero(keep)[0]
    shape = (len(ils), len(xls), info["ns"])
    with segyio.open(str(path), ignore_geometry=True) as f:
        t0 = float(f.samples[0])
    origin = (int(ils[0]), int(xls[0])) if origin_mode == "lines" else (0, 0)
    origin = (*origin, int(round(t0 / info["dt_ms"])) if info["dt_ms"] else 0)
    out_npy.parent.mkdir(parents=True, exist_ok=True)
    cube = np.lib.format.open_memmap(out_npy, mode="w+", dtype=np.float32, shape=shape)
    if fill:
        cube[:] = fill
    # trace_ids is ascending, so reading runs of consecutive trace numbers walks the file in order
    chunk = max(1, 50_000_000 // max(info["ns"], 1) // 4)  # ~200 MB of samples per read
    breaks = np.nonzero(np.diff(trace_ids) != 1)[0] + 1
    starts = np.r_[0, breaks]
    ends = np.r_[breaks, len(trace_ids)]
    done, next_log = 0, 0
    with segyio.open(str(path), ignore_geometry=True) as f:
        for s0, e0 in zip(starts, ends):
            for s in range(s0, e0, chunk):
                e = min(s + chunk, e0)
                a = int(trace_ids[s])
                cube[i_idx[s:e], x_idx[s:e]] = f.trace.raw[a:a + (e - s)]
                done += e - s
                if done >= next_log or done == len(trace_ids):
                    log(f"traces {done}/{len(trace_ids)}")
                    next_log = done + max(len(trace_ids) // 20, 1)
    cube.flush()
    del cube
    present = np.zeros(shape[:2], bool)
    present[i_idx, x_idx] = True
    missing = int((~present).sum())
    if missing:
        np.save(out_npy.with_name(out_npy.stem + "_trace_mask.npy"), present.astype(np.uint8))
    steps = lambda v: sorted({int(d) for d in np.diff(v)}) if len(v) > 1 else []  # noqa: E731
    result = {"source_segy": str(path), "npy": str(out_npy), "shape": list(shape),
              "axis_order": ["inline", "xline", "time"], "dtype": "float32",
              "inline_byte": int(inline_byte), "xline_byte": int(xline_byte),
              "inline": [int(ils[0]), int(ils[-1])], "xline": [int(xls[0]), int(xls[-1])],
              "inline_step": steps(ils), "xline_step": steps(xls),
              "dt_ms": info["dt_ms"], "t0_ms": t0, "time_ms": [t0, t0 + (shape[2] - 1) * info["dt_ms"]],
              "sample_format": info["format"], "traces_in_file": info["traces"], "traces_used": len(trace_ids),
              "missing_traces": missing, "fill_value": fill, "origin_mode": origin_mode,
              "origin_global_ixt": list(origin), "detected_line_bytes": cands[:4]}
    if len(result["inline_step"]) > 1 or len(result["xline_step"]) > 1:
        log("警告：线号间隔不均匀，数组下标与线号不是等间隔对应，见 info.json 的 inline_step / xline_step")
    elif origin_mode == "lines" and (result["inline_step"] not in ([], [1]) or result["xline_step"] not in ([], [1])):
        log(f"警告：线号间隔不是 1（inline {result['inline_step']}，xline {result['xline_step']}），"
            "数组下标 ≠ 线号 − 起点；再用本工具导出 SEG-Y 时线号会变成连续编号")
    if missing:
        log(f"警告：{missing} 道缺失，已填 {fill:g}，缺失位置见 {out_npy.stem}_trace_mask.npy")
    cb = COORD_PRESETS if coord_bytes == "auto" else [(*coord_bytes, "custom")]
    for xb, yb, desc in cb:
        x, y = coords(heads[trace_ids], xb, yb)
        if np.ptp(x) > 0 or np.ptp(y) > 0:
            def at(i, j):
                k = np.nonzero((i_idx == i) & (x_idx == j))[0]
                return [float(x[k[0]]), float(y[k[0]])] if len(k) else None
            li, lx = len(ils) - 1, len(xls) - 1
            result["coordinates"] = {"bytes": [xb, yb], "desc": desc, "scalar_byte": 71,
                                     "corners_xy": {"first_il_first_xl": at(0, 0), "first_il_last_xl": at(0, lx),
                                                    "last_il_first_xl": at(li, 0), "last_il_last_xl": at(li, lx)}}
            break
    info_path = out_npy.with_name(out_npy.stem + "_info.json")
    info_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"wrote {out_npy} {shape} + {info_path.name}")
    return result
