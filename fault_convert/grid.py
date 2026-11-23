"""Placement of a cube inside its survey (shared by SEG-Y export and TSurf rasterization)."""
import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Grid:
    origin: tuple = (0, 0, 0)  # global (inline, xline, sample) index of voxel [0, 0, 0]
    dt_ms: float = 2.0         # sample interval
    bin_m: float = 25.0        # synthetic bin size used for CDP_X / CDP_Y

    def __post_init__(self):
        self.origin = tuple(int(v) for v in self.origin)
        if len(self.origin) != 3:
            raise ValueError("origin needs 3 integers: inline, xline, sample")
        if self.dt_ms <= 0 or self.bin_m <= 0:
            raise ValueError("dt_ms and bin_m must be positive")

    def describe(self, shape):
        o = self.origin
        return {"inline": [o[0], o[0] + shape[0] - 1], "xline": [o[1], o[1] + shape[1] - 1],
                "time_ms": [o[2] * self.dt_ms, (o[2] + shape[2] - 1) * self.dt_ms]}

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def parse_origin(text):
        parts = [p for p in str(text).replace("，", ",").replace(" ", ",").split(",") if p]
        return tuple(int(p) for p in parts)


def grid_from_metadata(path, dt_ms=2.0, bin_m=25.0):
    """Read the origin from a sample's metadata.json / info.json if it has one.

    Understands FaultRegionExtractor metadata ("origin") and the info.json files written by
    this tool and the training scripts ("origin_global_ixt"). Returns None when nothing fits.
    """
    path = Path(path)
    if path.suffix == ".npy":  # <name>_info.json written by SEG-Y -> npy, then the folder's files
        candidates = [path.with_name(path.stem + "_info.json"), path.parent / "metadata.json", path.parent / "info.json"]
    elif path.is_file():
        candidates = [path]
    else:
        candidates = [path / "metadata.json", path / "info.json"]
    for c in candidates:
        if not c.is_file():
            continue
        try:
            meta = json.loads(c.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for key in ("origin", "origin_global_ixt"):
            if key in meta and len(meta[key]) == 3:
                dt = (meta.get("sampling") or {}).get("sample_interval_ms") or meta.get("dt_ms") or dt_ms
                return Grid(tuple(meta[key]), float(dt), bin_m)
    return None
