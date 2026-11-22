"""Regression test: the tool must reproduce the files made by hand for the X15 work (R0008 / R0009 / gap).

Run:  python tests/test_against_x15.py      (needs the F:\\FaultRegionExtractor and newinterX15 folders)
Writes temporary outputs to tests/_out (deleted at the end unless --keep).
"""
import shutil
import sys
from pathlib import Path

import numpy as np
import segyio

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fault_convert import Grid  # noqa: E402
from fault_convert.jobs import job_labels, job_overlay, job_segy  # noqa: E402

FRE = Path(r"F:\FaultRegionExtractor")
R9 = FRE / "问题样本" / "R0009_X15seismic_漏检"
R8_TS = Path(r"F:\SeismicData\newinterX15训练集_20261109\petrel导出")
GAP_TS = FRE / "petrel_import" / "gap_R0009_R0008" / "faults_ts"
STITCH = FRE / "training" / "R0009_gap_R0008_instance_20261121"
OUT = ROOT / "tests" / "_out"
quiet = lambda *a: None


def same_segy(a, b):
    with segyio.open(str(a)) as fa, segyio.open(str(b)) as fb:
        traces = np.array_equal(segyio.tools.cube(fa), segyio.tools.cube(fb))
        heads = all(dict(fa.header[i]) == dict(fb.header[i]) for i in range(0, fa.tracecount, 997))
        return traces and heads and fa.bin == fb.bin


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ok = True
    g9 = Grid((8, 124, 209), 2.0, 25.0)

    job_segy([R9 / "seismic.npy"], OUT, g9, verify=True, log=quiet)
    r = same_segy(OUT / "seismic.sgy", FRE / "petrel_import" / "R0009" / "R0009_X15_seismic.sgy")
    print("1 segy  : R0009 seismic SEG-Y identical to petrel_import/R0009 (traces, headers, binary header):", r)
    ok &= r

    job_overlay(R9 / "seismic.npy", R9 / "prediction.npy", OUT / "overlay.npy", segy_out=OUT / "overlay.sgy",
                grid=g9, log=quiet)
    r = same_segy(OUT / "overlay.sgy", FRE / "petrel_import" / "R0009" / "R0009_X15_overlay_p05.sgy")
    print("2 overlay: R0009 overlay SEG-Y identical to petrel_import/R0009/R0009_X15_overlay_p05.sgy:", r)
    ok &= r

    seis8 = OUT / "r8_shape.npy"
    np.save(seis8, np.zeros((128, 128, 699), np.float32))
    info = job_labels(R8_TS, seis8, OUT / "r8", Grid((233, 150, 461)), "both", start_id=136, log=quiet)
    b = np.load(OUT / "r8" / "fault_binary.npy")
    r1 = np.array_equal(b, np.load(FRE / "training" / "R0008" / "fault.npy"))
    inst_ref = np.load(STITCH / "fault_instance.npy", mmap_mode="r")
    r2 = np.array_equal(np.load(OUT / "r8" / "fault_instance.npy"), inst_ref[225:])
    print(f"3 labels: R0008 27 TS -> binary equal to training/R0008/fault.npy: {r1}; "
          f"instance (ids 136-162) equal to stitched instance IL 233-360: {r2}  ({info['n_faults']} faults)")
    ok &= r1 and r2

    seis_st = OUT / "st_shape.npy"
    np.save(seis_st, np.zeros((353, 128, 699), np.float32))
    job_labels(GAP_TS, seis_st, OUT / "gap", Grid((8, 150, 461)), "instance", start_id=121,
               inline_range=(220, 232), log=quiet)
    gi = np.load(OUT / "gap" / "fault_instance.npy")
    r = np.array_equal(gi[212:225], inst_ref[212:225]) and not gi[:212].any() and not gi[225:].any()
    print("4 labels: gap 15 TS with --inlines 220,232 -> instance equal to stitched IL 220-232 (ids 121-135):", r)
    ok &= r

    if "--keep" not in sys.argv:
        shutil.rmtree(OUT)
    print("ALL PASSED" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
