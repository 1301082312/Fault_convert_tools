"""Fault_convert_tools: probability overlay, npy -> SEG-Y, and Petrel TSurf -> npy fault labels.

All cubes are numpy arrays with axis order (inline, xline, time). A cube is placed in its parent
survey by `Grid`: the global (inline, xline, sample) index of its first voxel plus the sample
interval and bin size. These are the same conventions used for the X15 work:

    SEG-Y inline (byte 189)  = global inline index
    SEG-Y xline  (byte 193)  = global xline index
    CDP_X (byte 181) = xline * bin_m,  CDP_Y (byte 185) = inline * bin_m   (scalar -100)
    time of first sample     = origin_sample * dt_ms

so fault surfaces interpreted in Petrel on these SEG-Y files map straight back to npy indices.
"""
from .grid import Grid  # noqa: F401
from .overlay import make_overlay  # noqa: F401
from .segy import npy_to_segy, write_segy  # noqa: F401
from .tsurf import build_labels, read_tsurf  # noqa: F401

__version__ = "1.0.0"
