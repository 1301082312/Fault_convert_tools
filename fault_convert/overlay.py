"""Burn a fault probability cube into a seismic cube for viewing in Petrel.

seismic is clipped at its `clip_percentile` of |amplitude| and scaled to +-`scale`; voxels with
probability >= threshold become `fault_value` (+1). The last time sample is set to -1 so the
colour range stays symmetric around 0 in Petrel. The result is for display only: amplitudes are
compressed and overwritten at fault voxels.

Works inline by inline with a memory-mapped output, so a full survey (several GB) fits in RAM.
"""
from pathlib import Path

import numpy as np

FULL_PERCENTILE_LIMIT = 64_000_000  # voxels; larger cubes estimate the clip on a strided subset


def clip_value(seismic, percentile=99.0):
    n = seismic.size
    if n <= FULL_PERCENTILE_LIMIT:
        sample = np.abs(np.asarray(seismic, dtype=np.float32))
    else:
        step = int(np.ceil(np.sqrt(n / FULL_PERCENTILE_LIMIT)))
        sample = np.abs(np.asarray(seismic[::step, ::step], dtype=np.float32))
    return np.percentile(sample, percentile)  # float32 scalar, kept for bit-identical scaling


def make_overlay(seismic_path, probability_path, out_path, threshold=0.5, clip_percentile=99.0,
                 scale=0.6, fault_value=1.0, pin_last_sample=True, log=print):
    s = np.load(seismic_path, mmap_mode="r")
    p = np.load(probability_path, mmap_mode="r")
    if s.shape != p.shape:
        raise ValueError(f"seismic {s.shape} and probability {p.shape} must have the same shape")
    if s.ndim != 3:
        raise ValueError("cubes must be 3-D (inline, xline, time)")
    clip = clip_value(s, clip_percentile)
    if not np.isfinite(clip) or clip <= 0:
        raise ValueError("seismic clip value is zero or not finite")
    log(f"clip |amp| at {clip_percentile:g}th percentile = {clip:.6g}")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out = np.lib.format.open_memmap(out_path, mode="w+", dtype=np.float32, shape=s.shape)
    faults = 0
    for i in range(s.shape[0]):
        v = (np.clip(np.asarray(s[i], dtype=np.float32), -clip, clip) / clip * scale).astype(np.float32)
        m = np.asarray(p[i]) >= threshold
        v[m] = fault_value
        if pin_last_sample:
            v[:, -1] = -1.0
        out[i] = v
        faults += int(m.sum())
        if (i + 1) % 50 == 0 or i + 1 == s.shape[0]:
            log(f"overlay inline {i + 1}/{s.shape[0]}")
    out.flush()
    del out
    frac = faults / s.size
    log(f"wrote {out_path}  fault fraction {frac:.4f} (threshold {threshold:g})")
    return {"clip": float(clip), "fault_fraction": frac, "threshold": threshold, "path": str(out_path)}
