"""Regression test: the tool must reproduce reference files made earlier with the same rules.

Needs your own reference data, given on the command line (or in environment variables):

  python tests/test_against_x15.py --sample DIR --ref-seismic-sgy FILE --ref-overlay-sgy FILE
                                   --ts-a DIR --ref-binary-a FILE --ref-instance FILE --ts-b DIR [--keep]

  --sample            folder with seismic.npy, prediction.npy and metadata.json ("origin") of a sample
  --ref-seismic-sgy   SEG-Y written earlier from that sample's seismic.npy        (check 1)
  --ref-overlay-sgy   overlay SEG-Y written earlier from seismic + prediction       (check 2)
  --ts-a / --ref-binary-a / --origin-a / --shape-a
                      TSurf folder, its reference binary label, and that label's grid (check 3)
  --ref-instance / --instance-origin / --start-a / --start-b / --ts-b / --inlines-b
                      a stitched instance label: segment A (ids from --start-a) sits at the end of it,
                      segment B (folder --ts-b, ids from --start-b) is clipped to --inlines-b (check 4)

Each option can also be set as an environment variable FCT_<OPTION> (e.g. FCT_SAMPLE). Checks whose
inputs are missing are skipped. Temporary outputs go to tests/_out (deleted unless --keep).
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

import numpy as np
import segyio

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fault_convert import Grid  # noqa: E402
from fault_convert.jobs import job_labels, job_overlay, job_segy  # noqa: E402

OUT = ROOT / "tests" / "_out"
quiet = lambda *a: None  # noqa: E731


def parse():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    env = lambda name, default=None: os.environ.get("FCT_" + name.upper().replace("-", "_"), default)  # noqa: E731
    for name, default in (("sample", None), ("ref-seismic-sgy", None), ("ref-overlay-sgy", None),
                          ("ts-a", None), ("ref-binary-a", None), ("origin-a", None), ("shape-a", None),
                          ("ref-instance", None), ("instance-origin", None), ("start-a", "1"),
                          ("ts-b", None), ("start-b", "1"), ("inlines-b", None)):
        ap.add_argument("--" + name, default=env(name, default))
    ap.add_argument("--dt", type=float, default=float(env("dt", "2")))
    ap.add_argument("--bin", type=float, default=float(env("bin", "25")))
    ap.add_argument("--keep", action="store_true")
    return ap.parse_args()


def ints(text):
    return Grid.parse_origin(text)


KEY_BYTES = (71, 109, 115, 117, 181, 185, 189, 193)  # what the reference files define


def same_segy(a, b):
    """Samples, binary header and the geometry bytes equal; plus the Petrel default bytes
    (5 = inline, 17/21 = xline, 73/77 = X/Y) present in the new file."""
    with segyio.open(str(a)) as fa, segyio.open(str(b)) as fb:
        traces = np.array_equal(segyio.tools.cube(fa), segyio.tools.cube(fb))
        heads = extra = True
        for i in range(0, fa.tracecount, 997):
            ha, hb = fa.header[i], fb.header[i]
            heads &= all(ha[k] == hb[k] for k in KEY_BYTES)
            extra &= ha[5] == ha[189] and ha[17] == ha[21] == ha[193] and ha[73] == ha[181] and ha[77] == ha[185]
        return traces and heads and extra and fa.bin == fb.bin


def shape_file(shape, name):
    p = OUT / name
    np.save(p, np.zeros(shape, np.float32))  # only the shape is used
    return p


def main():
    a = parse()
    OUT.mkdir(parents=True, exist_ok=True)
    results = {}

    if a.sample:
        sample = Path(a.sample)
        origin = json.loads((sample / "metadata.json").read_text(encoding="utf-8"))["origin"]
        grid = Grid(tuple(origin), a.dt, a.bin)
        if a.ref_seismic_sgy:
            job_segy([sample / "seismic.npy"], OUT, grid, verify=True, log=quiet)
            results["1 seismic SEG-Y identical to reference"] = same_segy(OUT / "seismic.sgy", a.ref_seismic_sgy)
        if a.ref_overlay_sgy:
            job_overlay(sample / "seismic.npy", sample / "prediction.npy", OUT / "overlay.npy",
                        segy_out=OUT / "overlay.sgy", grid=grid, log=quiet)
            results["2 overlay SEG-Y identical to reference"] = same_segy(OUT / "overlay.sgy", a.ref_overlay_sgy)

    if a.ts_a and a.ref_binary_a and a.origin_a:
        ref_b = np.load(a.ref_binary_a, mmap_mode="r")
        shape = ints(a.shape_a) if a.shape_a else ref_b.shape
        start_a = int(a.start_a)
        job_labels(a.ts_a, shape_file(shape, "a_shape.npy"), OUT / "a", Grid(ints(a.origin_a), a.dt, a.bin),
                   "both", start_a, log=quiet)
        results["3a binary label identical to reference"] = bool(
            np.array_equal(np.load(OUT / "a" / "fault_binary.npy"), ref_b))
        if a.ref_instance:
            inst = np.load(a.ref_instance, mmap_mode="r")
            seg = inst[inst.shape[0] - shape[0]:]
            results["3b instance label identical to the end of the reference instance cube"] = bool(
                np.array_equal(np.load(OUT / "a" / "fault_instance.npy"), seg))

    if a.ts_b and a.ref_instance and a.instance_origin and a.inlines_b:
        inst = np.load(a.ref_instance, mmap_mode="r")
        o = ints(a.instance_origin)
        lo, hi = ints(a.inlines_b)[:2]
        job_labels(a.ts_b, shape_file(inst.shape, "b_shape.npy"), OUT / "b", Grid(o, a.dt, a.bin), "instance",
                   int(a.start_b), inline_range=(lo, hi), log=quiet)
        got = np.load(OUT / "b" / "fault_instance.npy")
        i0, i1 = lo - o[0], hi - o[0] + 1
        results["4 clipped instance segment identical to reference"] = bool(
            np.array_equal(got[i0:i1], inst[i0:i1]) and not got[:i0].any() and not got[i1:].any())

    if not a.keep:
        shutil.rmtree(OUT, ignore_errors=True)
    if not results:
        print("no reference data given; nothing checked (see --help)")
        return 0
    for k, v in results.items():
        print(f"{'PASS' if v else 'FAIL'}  {k}")
    ok = all(results.values())
    print("ALL PASSED" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
