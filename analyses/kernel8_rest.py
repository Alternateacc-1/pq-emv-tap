"""The rest of a Kernel 8 transaction, reader side.

Authentication is only part of a tap. The reader also has to activate the
card, select the payment application and send GENERATE AC, and EMV makes it
wait 5.1 ms twice while polling (L1 9.2.1.4, 9.3.2.1). This counts the
reader's frames, frame delays and waits for those steps at their smallest
allowed sizes, and adds them to every Kernel 8-style design.

Writes results/kernel8_rest.json (and a readable results/kernel8_rest.md).
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
T_P_MIN = F(51, 10000)          # 5.1 ms, Table A.7 (PCD min)
F9_LEFT = None                  # computed from the fit data

# (label, reader etu or 1/fc, clause) — Type A frames (L1 4.7.1)
ETU = F(128, FC)


def items(fsd):
    L = Link(fsd=fsd, fsc=fsd)
    rows = [
        ("HLTA ('50' '00' + CRC_A, standard frame, 4 bytes)", L.reader_frame(4),
         "L1 9.2.1.3 (after WUPA response, 'shall send a HLTA command'); 5.6.1"),
        ("WUPB (Type B: SoS ≥ 1280+248/fc, 5 characters × 10 etu, EGT ≥ 0, EoS ≥ 1280/fc)",
         F(1280 + 248, FC) + 5 * 10 * ETU + F(1280, FC),
         "L1 9.2.1.4 ('shall … send a WUPB command'); Table 6.2 (3 bytes + CRC_B); 4.7.2; Table A.6 tPCD,S,1/S,2/E minima"),
        ("WUPA (short frame: SoF + 7 bits + EoF)", 9 * ETU,
         "L1 9.3.2.1 ('before sending a WUPA command'); 4.7.1 short frame"),
        ("ANTICOLLISION CL1 (SEL '93', NVB '20'; standard frame without CRC_A, 2 bytes)", L.reader_frame(2),
         "L1 9.3.2.2; 5.4.1 Table 5.5"),
        ("SELECT CL1 (SEL, '70', UID CL1 5 bytes + CRC_A = 9 bytes; single-size UID)", L.reader_frame(9),
         "L1 9.3.2.3; 5.5.1"),
        ("RATS ('E0', PARAM + CRC_A = 4 bytes)", L.reader_frame(4),
         "L1 9.4.1.1; 5.7.1 Table 5.12"),
    ]
    apdus = [
        ("SELECT (PPSE): 00 A4 04 00 0E '2PAY.SYS.DDF01' 00 (20 bytes)", 20,
         "Book B 3.3.2.2 Step 1; Book 1 §11.3.2; 14-byte name (Book B §3.3.1)"),
        ("SELECT (AID): 4 + Lc + 5-byte ADF Name + Le (11 bytes)", 11,
         "Book B 3.3.3.4; ADF/DF Name 'var. 5 to 16' (C-8 A.1.50) — smallest 5"),
        ("GENERATE AC: 4 + Le, CDOL1 Related Data 0 bytes (5 bytes)", 5,
         "C-8 §5.3.2 Table 5.6; CDOL1 or Default CDOL1 must be non-empty (C-8 20.19, IsNotEmpty: length > 0) but the data it requests may be 0 bytes — smallest value taken"),
    ]
    for name, c, clause in apdus:
        rows.append((name, L.reader_frame(c + 3), clause))   # one block (≤ FSC)
    return rows


def remainder(fsd):
    rows = items(fsd)
    frames = sum(r[1] for r in rows)
    # card responses after the first ATQA: ATQA(1st, before HLTA), ATQA(2nd),
    # UID CL1, SAK, ATS, SELECT PPSE resp, SELECT AID resp, GENERATE AC resp
    n_gaps = 8
    gaps = n_gaps * F(6780, FC)
    tp = 2 * T_P_MIN
    return {"rows": rows, "frames": frames, "gaps": gaps, "n_gaps": n_gaps, "tp": tp,
            "R_frames_gaps": frames + gaps, "R_with_tp": frames + gaps + tp,
            "R_frames_only": frames}


def main():
    s4 = json.load(open(os.path.join(ROOT, "results", "fit_matrix.json"), encoding="utf-8"))
    out, md = {}, []
    rem = {fs: remainder(fs) for fs in (256, 512, 4096)}
    r = rem[256]
    md.append("### Mandatory remainder: reader-side items (lower bound)\n")
    md.append("| item | reader time ms | clause / size basis |\n|---|---|---|")
    for name, t, clause in r["rows"]:
        md.append("| %s | %s | %s |" % (name, R.ms(t, 4), clause))
    md.append("| FDT_A,PCD gaps × %d (after ATQA, ATQA, UID CL1, SAK, ATS, three R-APDUs) | %s | L1 4.8.2.1, Table A.6 (6780/fc) |"
              % (r["n_gaps"], R.ms(r["gaps"], 4)))
    md.append("| t_P × 2 (before WUPB, 9.2.1.4; before WUPA, 9.3.2.1), unmodulated carrier | %s | L1 9.2.1.4, 9.3.2.1; Table A.7 t_P PCD min 5.1 ms |"
              % R.ms(r["tp"], 4))
    md.append("")
    md.append("Mandatory non-certificate records: 0 extra READ RECORD exchanges — the "
              "only record object C-8 checks after reading records is the Application PAN "
              "(2627.1; A.1.16 '5A' ≤ 10 bytes), which fits in spare space of an already "
              "modelled record (Book 3 §7.1 allows several objects per record). EXCHANGE "
              "RELAY RESISTANCE DATA excluded: C-8 §3.6 \"The Kernel invokes RRP if both "
              "Card and Kernel support the procedure\" (optional). The first WUPA is "
              "excluded (the instruction counts only reader transmissions after the card's "
              "first response; Book A §10.1 starts the clock at that WUPA) — so R is a lower bound.\n")
    md.append("| FSD = FSC | frames ms | frames + FDT_A,PCD ms (R_min) | + 2 t_P ms (Figure 10-1) |\n|---|---|---|---|")
    for fs in (256, 512, 4096):
        x = rem[fs]
        md.append("| %d | %s | %s | %s |" % (fs, R.ms(x["frames"], 4), R.ms(x["R_frames_gaps"], 4), R.ms(x["R_with_tp"], 4)))
    md.append("")
    out["remainder"] = {str(fs): {"frames": R.frac(x["frames"]), "frames_ms": R.ms(x["frames"], 4),
                                  "R_min": R.frac(x["R_frames_gaps"]), "R_min_ms": R.ms(x["R_frames_gaps"], 4),
                                  "R_with_tp_ms": R.ms(x["R_with_tp"], 4)} for fs, x in rem.items()}

    # apply to every configuration that met all criteria in the fit matrix (EMV rate)
    rows, apply = [], []
    seen = set()
    for f in s4["fit"]:
        if f["div"] != 1 or not (f["all_ok"] or f["all_ok_t1b"]):
            continue
        key = (f["arch"], f["sig"], f["kem"], f["depth"], f["fs"])
        if key in seen:
            continue
        seen.add(key)
        ex, _, rops = R.build(f["arch"], f["sig"], f["kem"], f["depth"])
        link = Link(fsd=f["fs"], fsc=f["fs"])
        tot = closed_form(ex, link)
        reader_fixed = tot.reader_frames + tot.pcd_gaps * link.t_fdt_pcd
        rc = R.reader_cycle_total({"arch": f["arch"], "sig": f["sig"], "kem": f["kem"]}, rops)
        x = rem[f["fs"]]
        res = {}
        for mode, fixed, Rm in (("T1 frames+gaps", reader_fixed, x["R_frames_gaps"]),
                                ("T1 + t_P (Figure 10-1)", reader_fixed, x["R_with_tp"]),
                                ("T1b frames only", tot.reader_frames, x["R_frames_only"])):
            left = R.READER_BUDGET - fixed - Rm
            clk = None if (left <= 0 or rc is None) else R.mhz(ceil(F(rc) / left))
            res[mode] = {"left_ms": R.ms(left, 3), "reader_mhz": clk if left > 0 else "none (no reader clock)"}
        a = {"arch": f["arch"], "sig": f["sig"], "kem": f["kem"], "depth": f["depth"], "fs": f["fs"],
             "reader_fixed_ms": R.ms(reader_fixed), "reader_cycles": rc, "modes": res}
        apply.append(a)
        rows.append((f["arch"], f["sig"], f["kem"] or "", f["depth"] if f["depth"] == 2 else "1 (NON-STD)", f["fs"],
                     R.ms(reader_fixed), res["T1 frames+gaps"]["left_ms"], res["T1 frames+gaps"]["reader_mhz"],
                     res["T1 + t_P (Figure 10-1)"]["left_ms"], res["T1 + t_P (Figure 10-1)"]["reader_mhz"],
                     res["T1b frames only"]["left_ms"], res["T1b frames only"]["reader_mhz"]))
    out["applied"] = apply
    md.append("### Remainder applied to every configuration that met the criteria in the fit matrix (EMV rate)\n")
    md.append("| arch | signature | KEM | depth | FSD=FSC | modelled reader ms | left after R_min ms | reader MHz (M4) | left incl. t_P ms | reader MHz | left, frames only (D-T1b) ms | reader MHz |")
    md.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r_ in rows:
        md.append("| " + " | ".join(str(c) for c in r_) + " |")
    md.append("")

    # classical sanity
    cls = []
    for depth in (2, 1):
        ex, _, _ = R.build("C-classical", depth=depth)
        link = Link()
        tot = closed_form(ex, link)
        reader_fixed = tot.reader_frames + tot.pcd_gaps * link.t_fdt_pcd
        tot_r = reader_fixed + rem[256]["R_with_tp"]
        cls.append({"depth": depth, "reader_fixed_ms": R.ms(reader_fixed), "with_remainder_and_tp_ms": R.ms(tot_r),
                    "left_ms": R.ms(R.READER_BUDGET - tot_r)})
    out["classical"] = cls
    md.append("### Sanity check: classical ECC Kernel 8 (FSD 256)\n")
    md.append("| depth | modelled reader ms | + remainder incl. t_P ms | left for ECC reader computation ms |\n|---|---|---|---|")
    for c in cls:
        md.append("| %s | %s | %s | %s |" % (c["depth"] if c["depth"] == 2 else "1 (NON-STD)", c["reader_fixed_ms"],
                                            c["with_remainder_and_tp_ms"], c["left_ms"]))
    md.append("")
    with open(os.path.join(ROOT, "results", "kernel8_rest.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1, sort_keys=True, default=str)
        fh.write("\n")
    with open(os.path.join(ROOT, "results", "kernel8_rest.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(md).rstrip() + "\n")
    print("tables written:", len(md), "lines")


if __name__ == "__main__":
    main()
