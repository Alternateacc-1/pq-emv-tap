"""Hand check of the rest of a Kernel 8 transaction (T13).

The values below were worked out by hand (docs/hand_calculations.md, T13) and
typed in; they are not computed by the code they check. run.py stops if
analyses/kernel8_rmin.py, its JSON output or the model disagree with them.
"""
import json
import os
import sys
from fractions import Fraction as F
from math import ceil

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analyses")); sys.path.insert(0, os.path.join(ROOT, "tests"))

import run as R                                        # noqa: E402
import kernel8_rmin as RMIN                             # noqa: E402
from pqemv.transport import Link, closed_form          # noqa: E402

FC = 13_560_000

# ---- hand values, hand_calculations.md T13 ------------------------------------------
HAND_ETU = {"HLTA": 38, "WUPA": 9, "ANTICOLLISION CL1": 20, "SELECT CL1": 83,
            "RATS": 38, "SELECT (PPSE)": 209, "SELECT (AID)": 128, "GENERATE AC": 74}
HAND_GAPS = {"HLTA": 1, "WUPB (Type B)": 0, "WUPA": 1, "ANTICOLLISION CL1": 1, "SELECT CL1": 1,
             "RATS": 1, "SELECT (PPSE)": 1, "SELECT (AID)": 1, "GENERATE AC": 0}
HAND_WUPB_FC = 9208                     # 1280 + 248 + 5 x 1280 + 0 + 1280
HAND_FRAME_ETU_TOTAL = 599
HAND_FRAMES = F(19, 3000)               # 85 880 / fc
HAND_GAPS_S = F(7, 2000)                # 47 460 / fc
HAND_RMIN = F(59, 6000)                 # 133 340 / fc
HAND_RMIN_TP = F(601, 30000)
HAND_CMIN_FIXED = F(76403, 847500)      # 1 222 448 / fc
HAND_MARGIN = F(53, 3390000)            # 212 / fc
HAND_MARGIN_TP = F(-1381, 135600)
HAND_CYCLES = 1184779
HAND_CLOCK_HZ = 75_781_147_359


def check(name, got, want, res):
    if got != want:
        raise SystemExit("TEST %s FAILED: got %r, want %r" % (name, got, want))
    res.append(name)


def t13():
    res = []
    etu = F(128, FC)
    gap = F(6780, FC)
    tp = F(51, 10000)
    # per-row against the script's TERMS table
    frames = F(0)
    ngaps = 0
    for name, _b, e, g, _c, _s in RMIN.TERMS:
        if name.startswith("t_P"):
            continue
        if name.startswith("WUPB"):
            check("T13 WUPB 1/fc", RMIN.wupb_time() * FC, HAND_WUPB_FC, res)
            frames += RMIN.wupb_time()
        else:
            check("T13 %s etu" % name, e, HAND_ETU[name], res)
            frames += e * etu
        check("T13 %s gaps" % name, g, HAND_GAPS[name], res)
        ngaps += g
    check("T13 t_P count", sum(1 for t in RMIN.TERMS if t[0].startswith("t_P")), 2, res)
    check("T13 frame etu", sum(HAND_ETU.values()), HAND_FRAME_ETU_TOTAL, res)
    check("T13 frames", frames, HAND_FRAMES, res)
    check("T13 frames (hand)", F(HAND_FRAME_ETU_TOTAL * 128 + HAND_WUPB_FC, FC), HAND_FRAMES, res)
    check("T13 gaps", ngaps * gap, HAND_GAPS_S, res)
    check("T13 R_min", frames + ngaps * gap, HAND_RMIN, res)
    check("T13 R_min + t_P", frames + ngaps * gap + 2 * tp, HAND_RMIN_TP, res)
    # against the committed JSON
    j = json.load(open(os.path.join(ROOT, "results", "kernel8_rmin.json"), encoding="utf-8"))
    check("T13 JSON R_min", F(j["R_min_frames_gaps"]), HAND_RMIN, res)
    a = [x for x in j["applied"] if x["cfg"] == ["C-min", "FN-DSA-512", "ML-KEM-512", 2, 512]][0]
    check("T13 JSON MHz", a["mhz_fg"], R.mhz(HAND_CLOCK_HZ), res)
    check("T13 JSON cycles", a["reader_cycles"], HAND_CYCLES, res)
    # F9 margins against the model
    ex, _, rops = R.build("C-min", "FN-DSA-512", "ML-KEM-512", 2)
    L = Link(fsd=512, fsc=512)
    tot = closed_form(ex, L)
    fixed = tot.reader_frames + tot.pcd_gaps * L.t_fdt_pcd
    check("T13 C-min modelled reader", fixed, HAND_CMIN_FIXED, res)
    check("T13 C-min reader cycles",
          R.reader_cycle_total({"arch": "C-min", "sig": "FN-DSA-512", "kem": "ML-KEM-512"}, rops),
          HAND_CYCLES, res)
    m = R.READER_BUDGET - fixed - HAND_RMIN
    check("T13 margin", m, HAND_MARGIN, res)
    check("T13 margin + t_P", m - 2 * tp, HAND_MARGIN_TP, res)
    check("T13 clock", ceil(F(HAND_CYCLES) / m), HAND_CLOCK_HZ, res)
    return res


def main():
    res = t13()
    print("hand checks: %d passed (T13)" % len(res))
    return res


if __name__ == "__main__":
    main()
