"""Reader clocks for C-min when the reader checks the certificates after
the card-removal signal.

Kernel 8 shows "card read successfully" right after the GENERATE AC response
(Book C-8 v1.2, steps 26.18-26.19) and waits for the certificate results
later (S27-S29). Book A counts reader processing only up to that signal.
So only the encapsulation has to fit in the reader's 100 ms; the two
signature checks can come after. Uses the model in pqemv/ unchanged.

Run: python checks/reader_after_removal.py
"""
import os, sys
from fractions import Fraction as F
from math import ceil
REPO = sys.argv[1] if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]) else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, REPO); sys.path.insert(0, os.path.join(REPO, "analyses"))
os.chdir(REPO)
import run as R
from pqemv.transport import Link, closed_form
import kernel8_rmin as S
from pqemv import implementations as cat

enc = cat.reader_cycles("ML-KEM-512", "encaps")
ver = cat.reader_cycles("FN-DSA-512", "verify")
print("reader cycles: verify %d, encaps %d, paper total %d" % (ver, enc, 2 * ver + enc))
ETU = F(128, 13_560_000)
frames = sum((S.wupb_time() if n.startswith("WUPB") else e * ETU) for n, b, e, g, c, k in S.TERMS if not n.startswith("t_P"))
gaps = sum(g for n, b, e, g, c, k in S.TERMS if not n.startswith("t_P")) * S.GAP
for fs in (256, 512):
    ex, _, rops = R.build("C-min", "FN-DSA-512", "ML-KEM-512", 2)
    link = Link(fsd=fs, fsc=fs)
    tot = closed_form(ex, link)
    fixed = tot.reader_frames + tot.pcd_gaps * link.t_fdt_pcd
    for label, used, Rm in (("frames+gaps, no t_P", fixed, frames + gaps),
                            ("frames only (no delays, no waits)", tot.reader_frames, frames)):
        left = R.READER_BUDGET - used - Rm
        for rc_label, rc in (("2 verify + encaps", 2 * ver + enc), ("encaps only", enc)):
            print("FSD=%d %-34s left %s ms  %-18s %s MHz" % (fs, label, R.ms(left, 4), rc_label,
                  R.mhz(ceil(F(rc) / left)) if left > 0 else "none"))
