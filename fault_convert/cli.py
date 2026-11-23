"""Command line:  python -m fault_convert <overlay|segy|labels|tonpy> ...   (see README.md)"""
import argparse
import json
import sys

from .grid import Grid, grid_from_metadata
from .jobs import job_labels, job_overlay, job_segy


def resolve_grid(args, near):
    if args.origin:
        return Grid(Grid.parse_origin(args.origin), args.dt, args.bin)
    g = grid_from_metadata(near, args.dt, args.bin)
    if g is None:
        sys.exit("no --origin given and no metadata.json / info.json with an origin next to the input")
    print(f"origin from metadata: {g.origin}, dt {g.dt_ms} ms")
    return g


def add_grid(p):
    p.add_argument("--origin", help="global inline,xline,sample of voxel [0,0,0], e.g. 8,124,209 "
                                    "(default: read from metadata.json / info.json next to the input)")
    p.add_argument("--dt", type=float, default=2.0, help="sample interval in ms (default 2)")
    p.add_argument("--bin", type=float, default=25.0, help="synthetic bin size in m (default 25)")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="fault_convert", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("overlay", help="burn probability >= threshold into seismic (npy, optional SEG-Y)")
    p.add_argument("seismic"), p.add_argument("probability"), p.add_argument("out_npy")
    p.add_argument("--threshold", type=float, default=0.5)
    p.add_argument("--clip", type=float, default=99.0, help="clip percentile of |amplitude| (default 99)")
    p.add_argument("--scale", type=float, default=0.6, help="clipped seismic is scaled to +-scale (default 0.6)")
    p.add_argument("--segy", help="also write this SEG-Y")
    add_grid(p)

    p = sub.add_parser("segy", help="npy cube(s) -> SEG-Y for Petrel")
    p.add_argument("npy", nargs="+"), p.add_argument("--out-dir", required=True)
    p.add_argument("--no-verify", action="store_true", help="skip reading the SEG-Y back")
    add_grid(p)

    p = sub.add_parser("labels", help="Petrel TSurf (.ts) -> binary / instance label npy")
    p.add_argument("ts", help="folder of .ts files (natural name order = instance id order) or one .ts")
    p.add_argument("seismic", help="seismic npy that defines the output shape")
    p.add_argument("out_dir")
    p.add_argument("--mode", choices=["binary", "instance", "both"], default="both")
    p.add_argument("--start-id", type=int, default=1)
    p.add_argument("--inlines", help="keep only global inlines a,b (e.g. 220,232)")
    p.add_argument("--copy-seismic", action="store_true", help="also save seismic.npy into out_dir")
    add_grid(p)

    p = sub.add_parser("tonpy", help="SEG-Y -> npy (inline, xline, time) with header-byte auto-detection")
    p.add_argument("segy"), p.add_argument("out_npy")
    p.add_argument("--inline-byte", default="auto", help="e.g. 189, 9, 221 (default: auto-detect)")
    p.add_argument("--xline-byte", default="auto", help="e.g. 193, 21 (default: auto-detect)")
    p.add_argument("--coord-bytes", default="auto", help="X,Y bytes e.g. 181,185 or 73,77 (default: auto)")
    p.add_argument("--inlines", help="only inline numbers a,b")
    p.add_argument("--origin-mode", choices=["lines", "zero"], default="lines",
                   help="origin = first line numbers (round trip with this tool) or 0,0 (default lines)")
    p.add_argument("--fill", type=float, default=0.0, help="value for missing traces (default 0)")

    a = ap.parse_args(argv)
    if a.cmd == "tonpy":
        from .segy_read import segy_to_npy
        b = lambda v: v if v == "auto" else int(v)  # noqa: E731
        r = segy_to_npy(a.segy, a.out_npy, b(a.inline_byte), b(a.xline_byte),
                        a.coord_bytes if a.coord_bytes == "auto" else Grid.parse_origin(a.coord_bytes)[:2],
                        Grid.parse_origin(a.inlines)[:2] if a.inlines else None, a.origin_mode, a.fill)
        print(json.dumps({k: v for k, v in r.items() if k != "detected_line_bytes"}, ensure_ascii=False, indent=1))
        return
    from pathlib import Path
    from .segy import non_ascii_paths
    planned = [a.segy] if a.cmd == "overlay" and a.segy else \
        [Path(a.out_dir) / (Path(n).stem + ".sgy") for n in a.npy] if a.cmd == "segy" else []
    for p in non_ascii_paths(planned):
        print(f"警告：SEG-Y 路径含中文或其他非 ASCII 字符，Petrel 导入会出错，建议改用纯英文路径：{p}")
    if a.cmd == "overlay":
        grid = resolve_grid(a, a.seismic) if a.segy else None
        r = job_overlay(a.seismic, a.probability, a.out_npy, a.threshold, a.clip, a.scale, a.segy, grid)
    elif a.cmd == "segy":
        r = job_segy(a.npy, a.out_dir, resolve_grid(a, a.npy[0]), verify=not a.no_verify)
    else:
        rng = Grid.parse_origin(a.inlines)[:2] if a.inlines else None
        r = job_labels(a.ts, a.seismic, a.out_dir, resolve_grid(a, a.seismic), a.mode, a.start_id, rng,
                       a.copy_seismic)
        r = {k: v for k, v in r.items() if k != "faults"}
    print(json.dumps(r, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
