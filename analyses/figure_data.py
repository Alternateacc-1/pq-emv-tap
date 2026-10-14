"""Numbers the figures need that no other script stores.

1. For C-min with FN-DSA-512 and ML-KEM-512 at 512-byte frames: the reader's
   frames and frame delays separately (Fig. 3).
2. The card clock needed for the range of protected ML-KEM-512
   decapsulation costs from analyses/protected_mlkem.py (Fig. 5).

Writes results/figure_data.json.
"""
import json
import os
import sys
from fractions import Fraction as F
from math import ceil

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

import run as R                                        # noqa: E402
from pqemv.transport import Link, closed_form          # noqa: E402


def main():
    ex, _, _ = R.build("C-min", "FN-DSA-512", "ML-KEM-512", 2)
    L = Link(fsd=512, fsc=512)
    t = closed_form(ex, L)
    s8 = json.load(open(os.path.join(ROOT, "results", "protected_mlkem.json"), encoding="utf-8"))
    exd, _, _ = R.build("C-min", "FN-DSA-512", "ML-KEM-512", 2)
    L256 = Link()
    lo = ceil(F(s8["decaps_lo_cycles"]))
    hi = ceil(F(s8["decaps_hi_cycles"]))
    out = {
        "f9_fs512": {"reader_frames": R.frac(t.reader_frames), "pcd_gaps": t.pcd_gaps,
                     "pcd_gaps_s": R.frac(t.pcd_gaps * L.t_fdt_pcd)},
        "hardened_decaps_clock_hz": {
            "lo_cycles": lo, "hi_cycles": hi,
            "lo_hz": R.required_clock(exd, L256, {("decaps",): lo}, R.CARD_BUDGET),
            "hi_hz": R.required_clock(exd, L256, {("decaps",): hi}, R.CARD_BUDGET)},
    }
    with open(os.path.join(ROOT, "results", "figure_data.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
