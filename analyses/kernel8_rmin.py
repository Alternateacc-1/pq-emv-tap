"""R_min, the reader's share of the rest of a Kernel 8 transaction, term by term.

Each term is one reader frame or one frame delay, at the smallest size the
specifications allow. The result is applied to the closest Kernel 8-style
designs, with and without the two polling waits.

Writes results/kernel8_rmin.json (and a readable results/kernel8_rmin.md).
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

FC = 13_560_000
ETU = F(128, FC)
GAP = F(6780, FC)
T_P = F(51, 10000)

# (exchange, reader frame bytes, reader etu, gaps after card responses,
#  mandatory clause, FIXED/CHOSEN)
TERMS = [
    ("HLTA", "4 (2 + CRC_A)", 9 * 4 + 2, 1,
     "L1 9.2.1.3 'shall send a HLTA command'; gap after 1st ATQA (4.8.2.1)", "FIXED (5.6.1 two bytes + CRC_A)"),
    ("t_P before WUPB", "—", None, 0, "L1 9.2.1.4", "FIXED minimum 5.1 ms (Table A.7 PCD)"),
    ("WUPB (Type B)", "5 (3 + CRC_B)", None, 0,
     "L1 9.2.1.1 'shall poll for Type A and Type B', 9.2.1.4", "CHOSEN minimum: SoS 1280+248/fc, EoS 1280/fc, EGT 0 (Table A.6)"),
    ("t_P before WUPA", "—", None, 0, "L1 9.3.2.1", "FIXED minimum 5.1 ms"),
    ("WUPA", "short frame (7 bits)", 9, 1, "L1 9.3.2.1; gap after 2nd ATQA", "FIXED (4.7.1 short frame)"),
    ("ANTICOLLISION CL1", "2 (no CRC)", 9 * 2 + 2, 1, "L1 9.3.2.2; gap after UID CL1", "FIXED (5.4.1)"),
    ("SELECT CL1", "9 (7 + CRC_A)", 9 * 9 + 2, 1, "L1 9.3.2.3; gap after SAK", "CHOSEN minimum: single-size UID"),
    ("RATS", "4 (2 + CRC_A)", 9 * 4 + 2, 1, "L1 9.4.1.1; gap after ATS (4.8.2.5, SFGI 0)", "FIXED (5.7.1); SFGI 0 CHOSEN minimum"),
    ("SELECT (PPSE)", "23 (20 + PCB + CRC)", 9 * 23 + 2, 1,
     "Book B 3.3.2.1 (Start A/B: 'shall perform steps 1 to 3'), 3.3.2.2", "FIXED (14-byte name; Le per Book 1 §11.1.1)"),
    ("SELECT (AID)", "14 (11 + PCB + CRC)", 9 * 14 + 2, 1, "Book B 3.3.3.4", "CHOSEN minimum: 5-byte ADF Name (C-8 A.1.50)"),
    ("GENERATE AC", "8 (5 + PCB + CRC)", 9 * 8 + 2, 0,
     "C-8 §3.3, §5.3; last mandatory command — no FDT_A,PCD mandated after its response (4.8.2.1 applies only before a new command)",
     "CHOSEN minimum: CDOL1 Related Data 0 bytes"),
]


def wupb_time():
    return F(1280 + 248, FC) + 5 * 10 * ETU + F(1280, FC)


def main():
    rows = []
    frames = F(0)
    gaps_n = 0
    for name, byt, etu, g, clause, basis in TERMS:
        if name.startswith("t_P"):
            t = T_P
            rows.append((name, byt, "—", R.ms(t, 4), "0", clause, basis))
            continue
        t = wupb_time() if name.startswith("WUPB") else etu * ETU
        frames += t
        gaps_n += g
        rows.append((name, byt, "%s" % (etu if etu else "%s/fc" % (t * FC)), R.ms(t, 4),
                     "%d (%s ms)" % (g, R.ms(g * GAP, 4)), clause, basis))
    gaps = gaps_n * GAP
    r_fg = frames + gaps
    r_tp = r_fg + 2 * T_P
    out = {"frames_ms": R.ms(frames, 4), "gaps": gaps_n, "gaps_ms": R.ms(gaps, 4),
           "frames": R.frac(frames), "gaps_s": R.frac(gaps), "t_p": R.frac(T_P),
           "R_min_frames_gaps": R.frac(r_fg), "R_min_frames_gaps_ms": R.ms(r_fg, 4),
           "R_with_tp_ms": R.ms(r_tp, 4)}
    md = ["| exchange | reader frame bytes | etu | ms | gaps after card response (count, ms) | mandatory? | size |",
          "|---|---|---|---|---|---|---|"]
    md += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    md.append("| **Total** | | | frames %s | %d gaps, %s | | **R_min = %s ms; with t_P %s ms** |"
              % (R.ms(frames, 4), gaps_n, R.ms(gaps, 4), R.ms(r_fg, 4), R.ms(r_tp, 4)))
    # Without SELECT PPSE (if it were optional): for reference
    ppse = (9 * 23 + 2) * ETU + GAP
    out["R_min_without_PPSE_ms"] = R.ms(r_fg - ppse, 4)

    # apply to F9 and F15 configurations
    appl = []
    md2 = ["| arch | signature | KEM | depth | FSD=FSC | modelled reader ms | left after R_min (frames+gaps) ms | reader MHz (M4) | left incl. 2 t_P ms | reader MHz |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    cfgs = [("C-min", "FN-DSA-512", "ML-KEM-512", 2, 512), ("C-min", "FN-DSA-512", "ML-KEM-512", 2, 256),
            ("C-min", "FN-DSA-512", "ML-KEM-512", 1, 256), ("C-min", "FN-DSA-1024", "ML-KEM-512", 1, 256),
            ("C-min", "ML-DSA-44", "ML-KEM-512", 1, 512), ("C-min", "ML-DSA-65", "ML-KEM-512", 1, 512),
            ("C-min", "FN-DSA-512", "ML-KEM-512", 1, 512), ("C-min", "FN-DSA-1024", "ML-KEM-512", 1, 512)]
    for a, s, k, d, fs in cfgs:
        ex, _, rops = R.build(a, s, k, d)
        link = Link(fsd=fs, fsc=fs)
        tot = closed_form(ex, link)
        fixed = tot.reader_frames + tot.pcd_gaps * link.t_fdt_pcd
        rc = R.reader_cycle_total({"arch": a, "sig": s, "kem": k}, rops)
        res = []
        for Rm in (r_fg, r_tp):
            left = R.READER_BUDGET - fixed - Rm
            res.append((R.ms(left, 4), R.mhz(ceil(F(rc) / left)) if left > 0 else "none"))
        appl.append({"cfg": [a, s, k, d, fs], "reader_fixed_ms": R.ms(fixed), "left_fg_ms": res[0][0],
                     "mhz_fg": res[0][1], "left_tp_ms": res[1][0], "mhz_tp": res[1][1], "reader_cycles": rc})
        md2.append("| %s | %s | %s | %s | %d | %s | %s | %s | %s | %s |" % (
            a, s, k, d if d == 2 else "1 (NON-STD)", fs, R.ms(fixed), res[0][0], res[0][1], res[1][0], res[1][1]))
    out["applied"] = appl
    # classical sanity
    ex, _, _ = R.build("C-classical", depth=2)
    tot = closed_form(ex, Link())
    fixed = tot.reader_frames + tot.pcd_gaps * Link().t_fdt_pcd
    out["classical_left_with_tp_ms"] = R.ms(R.READER_BUDGET - fixed - r_tp, 3)
    with open(os.path.join(ROOT, "results", "kernel8_rmin.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
        fh.write("\n")
    with open(os.path.join(ROOT, "results", "kernel8_rmin.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(md) + "\n\n" + "\n".join(md2) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k != "applied"}, indent=1))
    for a in appl:
        print(a)


if __name__ == "__main__":
    main()
