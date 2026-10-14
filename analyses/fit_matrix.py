"""Which designs fit which payment chip.

1. For every architecture, signature, KEM, depth, bit rate and chip: does it
   meet the RAM, the card's 400 ms, the reader's 100 ms and the 500 ms
   card-in-field target, with any implementation that runs on the chip's core?
2. A term-by-term breakdown of the card clock FN-DSA-512 signing needs.
3. Kernel 8-style designs: reader transmission against frame delays.

Writes results/fit_matrix.json (and a readable results/fit_matrix.md).
"""
import json
import os
import sys
from fractions import Fraction as F

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

import run as R                                        # noqa: E402
from pqemv import implementations as cat                     # noqa: E402
from pqemv.transport import (Link, closed_form, evaluate_closed,   # noqa: E402
                             wtx_count, wtx_parts)

CHIPS = [  # (name, class, clock MHz, RAM KB) from the chip data briefs
    ("Infineon SLC37PDx (SC300)", "M3", 80, 16),
    ("Infineon SLC36PDx (SC300)", "M3", 80, 12),
    ("ST31N600 / STPay-Topaz-X1 (SC000)", "M0", 60, 16),
    ("ST31P450 / STPay-Topaz-1 (SC000)", "M0", 55, 10),
]
RANK = {"M0": 0, "M3": 1, "M4": 2}


def T(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join("" if c is None else str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def impls_for(ops):
    """Map impl id -> {op key: impl} when the id covers every op."""
    by = {}
    for i in cat.card_impls():
        for op, scheme in ops:
            if i["scheme"] == scheme and i["op"] == op:
                by.setdefault(i["id"], {})[(op,)] = i
    return {k: v for k, v in by.items() if len(v) == len(ops)}


def decompose(ex, link, cycles, f):
    """Card-side terms at clock f (D-T1, D-W1 pause)."""
    tot = closed_form(ex, link)
    wc, wr = wtx_parts(link)
    terms = {"card_frames": tot.card_frames,
             "fdt_picc_gaps": tot.picc_gaps * link.t_fdt_picc,
             "picc_gap_count": tot.picc_gaps}
    comp, wtx_card, ns = F(0), F(0), []
    for k in tot.compute_slots:
        tc = F(cycles[k], f)
        n = wtx_count(tc, link.fwt_card)
        ns.append(n)
        comp += max(link.t_fdt_picc, tc)
        wtx_card += n * wc
    terms.update({"computation": comp, "wtx_card": wtx_card, "wtx_n": ns,
                  "wtx_reader": sum(ns) * wr})
    terms["card_total"] = terms["card_frames"] + terms["fdt_picc_gaps"] + comp + wtx_card
    return terms


def main():
    out = {}
    md = []

    # ------------------------------------------------ 2. FN-DSA-512 decomposition
    L = Link()
    rows = []
    dec = []
    for arch in ("A", "B"):
        for depth in (2, 1):
            ex, _, _ = R.build(arch, "FN-DSA-512", None, depth)
            for iid in ("pqm4 ref", "Pornin 2026 RAM-efficient", "pqm4 m4f"):
                imp = impls_for([("sign", "FN-DSA-512")])[iid]
                cyc = {k: v["cycles"] for k, v in imp.items()}
                f = R.required_clock(ex, L, cyc, R.CARD_BUDGET)
                t = decompose(ex, L, cyc, f)
                fixed = t["card_frames"] + t["fdt_picc_gaps"]
                rec = {"arch": arch, "depth": depth, "impl": iid, "cycles": cyc[("sign",)],
                       "runs_on": list(next(iter(imp.values()))["runs_on"]),
                       "required_hz": f,
                       "card_frames_ms": R.ms(t["card_frames"]),
                       "fdt_picc_ms": R.ms(t["fdt_picc_gaps"]), "picc_gaps": t["picc_gap_count"],
                       "fixed_ms": R.ms(fixed),
                       "budget_left_ms": R.ms(R.CARD_BUDGET - fixed),
                       "wtx_n": t["wtx_n"], "wtx_card_ms": R.ms(t["wtx_card"], 6),
                       "computation_ms": R.ms(t["computation"], 6),
                       "card_total_ms": R.ms(t["card_total"], 6)}
                dec.append(rec)
                rows.append((arch, depth, iid, "/".join(rec["runs_on"]), rec["cycles"], rec["card_frames_ms"],
                             "%s (%d gaps)" % (rec["fdt_picc_ms"], rec["picc_gaps"]), rec["fixed_ms"],
                             rec["budget_left_ms"], rec["wtx_n"][0], rec["wtx_card_ms"], rec["computation_ms"],
                             rec["card_total_ms"], R.mhz(f)))
    out["fndsa512_decomposition"] = dec
    md.append("### FN-DSA-512 card clock decomposition\n")
    md.append(T(["arch", "depth", "implementation", "executes on", "sign cycles", "card frames ms",
                 "FDT_PICC ms", "fixed ms", "400 − fixed ms", "S(WTX) n", "S(WTX) card ms",
                 "computation ms", "card total ms", "clock MHz"], rows))
    md.append("")

    # ------------------------------------------------ 3. C reader tariff with/without gaps
    rows = []
    cre = []
    for depth in (2, 1):
        for a in ("C-min", "C-priv"):
            for k in cat.KEMS:
                for s in cat.SIGS:
                    ex, _, rops = R.build(a, s, k, depth)
                    tot = closed_form(ex, L)
                    tx = tot.reader_frames
                    gaps = tot.pcd_gaps * L.t_fdt_pcd
                    rc = R.reader_cycle_total({"arch": a, "sig": s, "kem": k}, rops)
                    rec = {"arch": a, "sig": s, "kem": k, "depth": depth,
                           "reader_tx_ms": R.ms(tx), "fdt_pcd_ms": R.ms(gaps),
                           "exceeds_with_gaps": tx + gaps >= R.READER_BUDGET,
                           "exceeds_tx_only": tx >= R.READER_BUDGET,
                           "reader_cycles_m4": rc}
                    cre.append(rec)
                    if s == "FN-DSA-512" or depth == 2 and s == "ML-DSA-44":
                        rows.append((a, s, k, depth, rec["reader_tx_ms"], rec["fdt_pcd_ms"],
                                     R.ms(tx + gaps), "yes" if rec["exceeds_with_gaps"] else "no",
                                     "yes" if rec["exceeds_tx_only"] else "no"))
    out["c_reader"] = cre
    md.append("### Architecture C: reader transmission vs FDT_A,PCD gaps\n")
    md.append(T(["arch", "signature", "KEM", "depth", "reader frames ms", "FDT_A,PCD gaps ms",
                 "sum ms", "≥100 with gaps (D-T1)", "≥100 frames only (D-T1b)"], rows))
    md.append("")

    # ------------------------------------------------ 1. fit matrix
    fit = []
    scen = []
    for a in ("A", "B"):
        for s in cat.SIGS + cat.R2SIGS:
            scen.append((a, s, None))
    for a in ("C-min", "C-priv"):
        for k in cat.KEMS:
            for s in cat.SIGS:
                scen.append((a, s, k))
    variants = [(1, 256), (2, 256), (4, 256), (8, 256), (1, 512), (1, 4096)]
    for div, fs in variants:
        link = Link(divisor=div, fsd=fs, fsc=fs)
        for depth in (2, 1):
            for a, s, k in scen:
                ex, _, rops = R.build(a, s, k, depth)
                sc = {"arch": a, "sig": s, "kem": k}
                ops = R.card_ops_for(sc)
                rc = R.reader_cycle_total(sc, rops)
                for cname, cls, mhz_, ramkb in CHIPS:
                    for iid, imp in impls_for(ops).items():
                        first = next(iter(imp.values()))
                        if cls not in first["runs_on"]:
                            continue
                        req = [R.ram_required(v) for v in imp.values()]
                        ram_ok = None if any(x is None for x in req) else max(req) <= ramkb * 1024
                        cyc = {kk: v["cycles"] for kk, v in imp.items()}
                        tot = closed_form(ex, link)
                        ev = evaluate_closed(tot, link,
                                             {kk: F(c, mhz_ * 1_000_000) for kk, c in cyc.items()})
                        card_ok = ev["card"] <= R.CARD_BUDGET
                        reader_fixed = ev["reader"]
                        reader_ok = reader_fixed < R.READER_BUDGET
                        # D-T1b: frame-delay gaps assigned to neither tariff
                        n_wtx = sum(ev["wtx"])
                        card_t1b = ev["card"] - tot.picc_gaps * link.t_fdt_picc
                        reader_t1b = (tot.reader_frames + n_wtx * link.reader_frame(4))
                        t1b_ok = (card_t1b <= R.CARD_BUDGET and reader_t1b < R.READER_BUDGET)
                        r_mhz_t1b = (None if (rc is None or reader_t1b >= R.READER_BUDGET) else
                                     R.mhz(R.reader_clock(reader_t1b, rc)))
                        r_mhz = (None if (rc is None or not reader_ok) else
                                 R.mhz(R.reader_clock(reader_fixed, rc)))
                        field = ev["card"] + reader_fixed
                        field_ok = field <= R.FIELD_BUDGET
                        basis = ("measured" if first["measured_on"] == cls else
                                 "LB" if RANK[first["measured_on"]] > RANK[cls] else "other")
                        rec = {"div": div, "fs": fs, "depth": depth, "arch": a, "sig": s, "kem": k, "chip": cname,
                               "impl": iid, "basis": basis, "ram_ok": ram_ok, "card_ok": card_ok,
                               "card_ms": R.ms(ev["card"]), "reader_fixed_ms": R.ms(reader_fixed),
                               "reader_ok": reader_ok, "reader_mhz_m4": r_mhz,
                               "field_ms": R.ms(field), "field_ok": field_ok,
                               "all_ok": bool(ram_ok) and card_ok and reader_ok and field_ok,
                               "card_t1b_ms": R.ms(card_t1b), "reader_t1b_ms": R.ms(reader_t1b),
                               "reader_mhz_m4_t1b": r_mhz_t1b,
                               "all_ok_t1b": bool(ram_ok) and t1b_ok}
                        fit.append(rec)
    out["fit"] = fit

    def summary(div, depth, need_measured):
        rows = []
        for r in fit:
            if r["div"] == div and r["fs"] == 256 and r["depth"] == depth and r["all_ok"] and (r["basis"] == "measured" or not need_measured):
                rows.append((r["arch"], r["sig"], r["kem"] or "", r["chip"], r["impl"], r["basis"],
                             r["card_ms"], r["reader_fixed_ms"], r["reader_mhz_m4"], r["field_ms"]))
        return rows

    for div in (1, 2, 4, 8):
        for depth in (2, 1):
            rows = summary(div, depth, False)
            label = "EMV rate" if div == 1 else "D=%d (out of EMV L1)" % div
            md.append("### Configurations meeting RAM + card 400 + reader 100 + field 500: %s, depth %d%s\n"
                      % (label, depth, "" if depth == 2 else " (NON-STANDARD)"))
            md.append(T(["arch", "signature", "KEM", "chip", "card implementation", "basis", "card ms",
                         "reader fixed ms", "reader MHz (M4)", "field ms (reader compute excl.)"], rows)
                      if rows else "**None.**")
            md.append("")

    for depth in (2, 1):
        rows = [(r["arch"], r["sig"], r["kem"] or "", r["chip"], r["impl"], r["basis"], r["card_t1b_ms"],
                 r["reader_t1b_ms"], r["reader_mhz_m4_t1b"], r["field_ms"])
                for r in fit if r["div"] == 1 and r["fs"] == 256 and r["depth"] == depth and r["all_ok_t1b"]]
        md.append("### EMV rate, depth %d%s, gaps assigned to neither tariff (D-T1b): configurations meeting RAM + card 400 + reader 100\n"
                  % (depth, "" if depth == 2 else " (NON-STANDARD)"))
        md.append(T(["arch", "signature", "KEM", "chip", "card implementation", "basis", "card ms (no gaps)",
                     "reader ms (no gaps)", "reader MHz (M4)", "field ms incl. gaps, excl. reader compute"], rows)
                  if rows else "**None.**")
        md.append("")

    for fs in (512, 4096):
        for depth in (2, 1):
            for mode, lab in (("all_ok", "D-T1"), ("all_ok_t1b", "D-T1b")):
                rows = [(r["arch"], r["sig"], r["kem"] or "", r["chip"], r["impl"], r["basis"],
                         r["card_ms"] if mode == "all_ok" else r["card_t1b_ms"],
                         r["reader_fixed_ms"] if mode == "all_ok" else r["reader_t1b_ms"],
                         r["reader_mhz_m4"] if mode == "all_ok" else r["reader_mhz_m4_t1b"], r["field_ms"])
                        for r in fit if r["div"] == 1 and r["fs"] == fs and r["depth"] == depth and r[mode]]
                md.append("### EMV rate, FSD = FSC = %d (permitted by L1 Tables 5.14/5.17), short APDUs, depth %d%s, %s\n"
                          % (fs, depth, "" if depth == 2 else " (NON-STANDARD)", lab))
                md.append(T(["arch", "signature", "KEM", "chip", "card implementation", "basis", "card ms",
                             "reader ms", "reader MHz (M4)", "field ms incl. gaps, excl. reader compute"], rows)
                          if rows else "**None.**")
                md.append("")

    # frontier table: minimal divisor per configuration (D-T1 and D-T1b), depth 2 and 1
    rows = []
    front = []
    for a, s, k in scen:
        for depth in (2, 1):
            cell = {}
            for mode in ("all_ok", "all_ok_t1b"):
                ok = [r for r in fit if r["fs"] == 256 and r["depth"] == depth and r["arch"] == a and r["sig"] == s
                      and r["kem"] == k and r[mode] and r["basis"] in ("measured", "LB")]
                ok_meas = [r for r in ok if r["basis"] == "measured"]
                cell[mode] = (min(r["div"] for r in ok_meas) if ok_meas else None,
                              min(r["div"] for r in ok) if ok else None)
            front.append({"arch": a, "sig": s, "kem": k, "depth": depth,
                          "min_div_T1_measured": cell["all_ok"][0], "min_div_T1_any": cell["all_ok"][1],
                          "min_div_T1b_measured": cell["all_ok_t1b"][0], "min_div_T1b_any": cell["all_ok_t1b"][1]})
            def f(x):
                return "never (D≤8)" if x is None else ("1 (EMV)" if x == 1 else str(x))
            rows.append((a, s, k or "", depth, f(cell["all_ok"][0]), f(cell["all_ok"][1]),
                         f(cell["all_ok_t1b"][0]), f(cell["all_ok_t1b"][1])))
    out["frontier_divisor"] = front
    md.append("### Frontier: smallest bit-rate divisor D at which some payment chip meets RAM + card + reader\n")
    md.append("D = 1 is EMV (106 kbit/s); D = 2, 4, 8 are outside EMV L1 v4.0. 'measured' uses only cycle counts "
              "measured on the chip's core class; 'incl. LB' also admits Cortex-M4/M3 lower-bound figures. "
              "Depth 1 is NON-STANDARD.\n")
    md.append(T(["arch", "signature", "KEM", "depth", "D (D-T1, measured)", "D (D-T1, incl. LB)",
                 "D (D-T1b, measured)", "D (D-T1b, incl. LB)"], rows))
    md.append("")

    # frontier: for each arch at EMV rate depth 2, which single criterion fails first per best config
    fr = []
    for a, s, k in scen:
        recs = [r for r in fit if r["div"] == 1 and r["fs"] == 256 and r["depth"] == 2 and r["arch"] == a and r["sig"] == s and r["kem"] == k]
        fails = {"ram": all(not r["ram_ok"] for r in recs) if recs else None,
                 "card": all(not r["card_ok"] for r in recs) if recs else None,
                 "reader": all(not r["reader_ok"] for r in recs) if recs else None,
                 "field": all(not r["field_ok"] for r in recs) if recs else None}
        fr.append({"arch": a, "sig": s, "kem": k, "fails_everywhere": fails})
    out["frontier_depth2"] = fr

    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    with open(os.path.join(ROOT, "results", "fit_matrix.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=1, sort_keys=True, default=str)
        f.write("\n")
    with open(os.path.join(ROOT, "results", "fit_matrix.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(md).rstrip() + "\n")
    print("fit rows", len(fit))


if __name__ == "__main__":
    main()
