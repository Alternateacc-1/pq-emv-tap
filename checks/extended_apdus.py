"""C-min with extended-length APDUs.

EMV Book 1 limits a response to 256 data bytes and a command to 255, so the
model splits every post-quantum object. Extended-length APDUs (outside Book 1
and Book 3's record rule) with frames above 256 bytes (optional in L1)
remove most of those exchanges. This adds the mandatory rest of the
transaction and both polling waits and prints what is left of the reader's
100 ms. Uses the model in pqemv/ unchanged.

Run: python checks/extended_apdus.py
"""
import os, sys
from fractions import Fraction as F
from math import ceil
REPO = sys.argv[1] if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]) else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, REPO); sys.path.insert(0, os.path.join(REPO, "analyses")); os.chdir(REPO)
import run as R
from pqemv.transport import Link, closed_form
import kernel8_rmin as S
from pqemv import implementations as cat
ETU = F(128, 13_560_000)
frames = sum((S.wupb_time() if n.startswith("WUPB") else e * ETU) for n, b, e, g, c, k in S.TERMS if not n.startswith("t_P"))
gaps = sum(g for n, b, e, g, c, k in S.TERMS if not n.startswith("t_P")) * S.GAP
rmin_tp = frames + gaps + 2 * S.T_P
print("R_min + 2 t_P = %s ms" % R.ms(rmin_tp, 4))
enc = cat.reader_cycles("ML-KEM-512", "encaps")
for sig in ("FN-DSA-512", "ML-DSA-44", "FN-DSA-1024", "ML-DSA-65", "ML-DSA-87"):
    for kem in ("ML-KEM-512", "ML-KEM-768"):
        for fs in (256, 512, 1024, 4096):
            ex, _, rops = R.build("C-min", sig, kem, 2, extended=True)
            link = Link(fsd=fs, fsc=fs)
            tot = closed_form(ex, link)
            fixed = tot.reader_frames + tot.pcd_gaps * link.t_fdt_pcd
            left = R.READER_BUDGET - fixed - rmin_tp
            rc = R.reader_cycle_total({"arch": "C-min", "sig": sig, "kem": kem}, rops)
            enc_k = cat.reader_cycles(kem, "encaps")
            mhz = lambda c: R.mhz(ceil(F(c) / left)) if left > 0 else "none"
            print("%-11s %-10s FS=%4d auth %8s total %8s left %8s | all PQ %s MHz | encaps only %s MHz"
                  % (sig, kem, fs, R.ms(fixed), R.ms(fixed + rmin_tp), R.ms(left), mhz(rc), mhz(enc_k)))
