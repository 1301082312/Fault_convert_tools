"""The three jobs as plain functions with file outputs; used by both the CLI and the GUI."""
import json
from pathlib import Path

import numpy as np

from .grid import Grid
from .overlay import make_overlay
from .segy import check_segy, npy_to_segy
from .tsurf import build_labels


def job_overlay(seismic, probability, out_npy, threshold=0.5, clip_percentile=99.0, scale=0.6,
                segy_out=None, grid=None, log=print):
    info = make_overlay(seismic, probability, out_npy, threshold, clip_percentile, scale, log=log)
    if segy_out:
        npy_to_segy(out_npy, segy_out, grid or Grid(), log=log)
        info["segy"] = str(segy_out)
    return info


def job_segy(npy_files, out_dir, grid, verify=True, log=print):
    out_dir = Path(out_dir)
    results = []
    for npy in npy_files:
        out = out_dir / (Path(npy).stem + ".sgy")
        npy_to_segy(npy, out, grid, log=log)
        r = {"npy": str(npy), "segy": str(out)}
        if verify:
            r.update(check_segy(out, npy))
            log(f"check {out.name}: IL {r['inline']} XL {r['xline']} {r['time_ms']} ms, "
                f"equal to npy: {r['equal_to_npy']}")
        results.append(r)
    return results


def job_labels(ts_source, seismic, out_dir, grid, mode="both", start_id=1, inline_range=None,
               copy_seismic=False, log=print):
    """mode: 'binary', 'instance' or 'both'. Shape is taken from the seismic npy."""
    s = np.load(seismic, mmap_mode="r")
    if s.ndim != 3:
        raise ValueError("seismic must be 3-D (inline, xline, time)")
    log(f"seismic {Path(seismic).name} shape {s.shape}, grid {grid.to_dict()}")
    inst, report = build_labels(ts_source, grid, s.shape, start_id, inline_range, log=log)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    binary = (inst > 0).astype(np.uint8)
    written = []
    if mode in ("binary", "both"):
        np.save(out_dir / "fault_binary.npy", binary)
        written.append("fault_binary.npy")
    if mode in ("instance", "both"):
        np.save(out_dir / "fault_instance.npy", inst)
        written.append("fault_instance.npy")
    if copy_seismic:
        np.save(out_dir / "seismic.npy", np.ascontiguousarray(np.asarray(s, dtype=np.float32)))
        written.append("seismic.npy")
    info = {"seismic_source": str(seismic), "fault_source": str(ts_source), "shape": list(s.shape),
            "axis_order": ["inline", "xline", "time"], "grid": grid.to_dict(),
            "origin_global_ixt": list(grid.origin), **grid.describe(s.shape),
            "inline_range_kept": list(inline_range) if inline_range else None,
            "files": written, "fault_fraction": float(binary.mean()),
            "n_faults": len(report), "empty_or_outside": [r["id"] for r in report if r["voxels"] == 0],
            "rule": "TSurf triangles rasterized in (inline, sample); xline span to halfway toward "
                    "neighbours, >= 2 traces; inline jumps > 12 and sample jumps > 3 traces not bridged",
            "overlap_rule": "voxel keeps the id written first", "faults": report}
    (out_dir / "label_info.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"wrote {', '.join(written)} + label_info.json to {out_dir}; fault fraction {info['fault_fraction']:.4f}")
    return info
