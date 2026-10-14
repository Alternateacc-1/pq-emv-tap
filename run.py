"""Run everything:  python run.py   (or  python run.py --write  to update results/)

1. If pqm4 and pqm3 are cloned into sources/, re-read their benchmark tables
   and check they match data/.
2. Reproduce the hand calculations in docs/hand_calculations.md.
3. Time every configuration twice, in closed form and frame by frame, and
   stop if the two ever disagree.
4. Check results/results.json, run the analyses in analyses/, the hand check
   in tests/, and check that paper/numbers.tex and the figure data come out
   exactly as committed.

All arithmetic is exact (fractions.Fraction).
"""
import json
import os
import subprocess
import sys
from fractions import Fraction as F
from math import ceil

from pqemv import architectures as ar
from pqemv import implementations as cat
from pqemv.transport import (Link, closed_form, evaluate_closed, simulate,
                             wtx_count, wtx_parts, FDT_PICC_ALT)

ROOT = os.path.dirname(os.path.abspath(__file__))
CARD_BUDGET = F(400, 1000)     # Book A 10.2 (implied card tariff)
READER_BUDGET = F(100, 1000)   # Book A 10.2.1.1
FIELD_BUDGET = F(500, 1000)    # Book A 10.1
KB = 1024                      # D-M2
APDU_BUF = 261                 # D-M1
MSG = 32                       # D-M1
SS = 32
RAM_SIZES = [10, 12, 14, 16]   # KB, from the chip data briefs


# ------------------------------------------------------------------ helpers

def ms(x, nd=3):
    """Exact Fraction seconds -> milliseconds string, rounded half up."""
    v = x * 1000
    q = F(10) ** nd
    r = (v * q + F(1, 2)).__floor__() if v >= 0 else -((-v * q + F(1, 2)).__floor__())
    s = str(abs(r)).rjust(nd + 1, "0")
    return ("-" if r < 0 else "") + s[:-nd] + "." + s[-nd:]


def mhz(hz, nd=3):
    """Hz -> MHz string (ms() multiplies by 1000, so pass Hz / 1e9)."""
    return ms(F(hz, 10 ** 9), nd)


def frac(x):
    return "%d/%d" % (x.numerator, x.denominator)


# --------------------------------------------------------------- core model

def evaluate(exchanges, link, cycles, f_card, pause=True):
    """Closed form and simulation at card clock f_card; must agree."""
    tot = closed_form(exchanges, link)
    ct = {k: F(c, f_card) for k, c in cycles.items()}
    a = evaluate_closed(tot, link, ct, pause)
    b = simulate(exchanges, link, ct, pause)
    if a["card"] != b["card"] or a["reader"] != b["reader"] or a["wtx"] != b["wtx"]:
        raise SystemExit("closed form != simulation: %r vs %r" % (a, b))
    return tot, a


def fixed_times(exchanges, link):
    """Card and reader time with zero computation (infinitely fast card)."""
    tot = closed_form(exchanges, link)
    a = evaluate_closed(tot, link, {k: F(0) for k in tot.compute_slots})
    b = simulate(exchanges, link, {k: F(0) for k in tot.compute_slots})
    if a["card"] != b["card"] or a["reader"] != b["reader"]:
        raise SystemExit("closed form != simulation (zero computation): %r vs %r" % (a, b))
    return tot, a["card"], a["reader"]


def required_clock(exchanges, link, cycles, budget, pause=True):
    """Minimum integer card clock (Hz) with card time <= budget, or None."""
    tot, card0, _ = fixed_times(exchanges, link)
    if card0 >= budget:
        return None

    def ok(f):
        return evaluate_closed(tot, link, {k: F(c, f) for k, c in cycles.items()}, pause)["card"] <= budget
    hi = 1_000_000
    while not ok(hi):
        hi *= 2
    lo = 1
    while lo < hi:
        mid = (lo + hi) // 2
        if ok(mid):
            hi = mid
        else:
            lo = mid + 1
    # T12: f* fits, f*-1 does not
    if not (ok(lo) and (lo == 1 or not ok(lo - 1))):
        raise SystemExit("required_clock: bisection did not converge")
    return lo


def reader_clock(reader_fixed, reader_cyc, budget=READER_BUDGET):
    if reader_fixed >= budget:
        return None
    return ceil(F(reader_cyc) / (budget - reader_fixed))


# ------------------------------------------------------------- scenarios

def build(arch, sig=None, kem=None, depth=2, fmt="E", extended=False):
    S = cat.SIZES.get(sig)
    K = cat.SIZES.get(kem)
    if arch == "A":
        return ar.arch_A(S, depth, fmt, extended)
    if arch == "B":
        return ar.arch_B(S, depth, fmt, extended)
    if arch == "A-classical":
        return ar.arch_A(None, depth, classical=True)
    if arch == "B-classical":
        return ar.arch_B(None, depth, classical=True)
    if arch == "C-classical":
        return ar.arch_C_classical(depth)
    if arch == "C-min":
        return ar.arch_C_min(S, K, depth, fmt, extended)
    if arch == "C-priv":
        return ar.arch_C_priv(S, K, depth, fmt, extended)
    raise KeyError(arch)


def scenarios():
    out = []
    for d in (2, 1):
        for a in ("A-classical", "B-classical", "C-classical"):
            out.append({"arch": a, "sig": None, "kem": None, "depth": d})
        for a in ("A", "B"):
            for s in cat.SIGS + cat.R2SIGS:
                out.append({"arch": a, "sig": s, "kem": None, "depth": d})
        for a in ("C-min", "C-priv"):
            for k in cat.KEMS:
                for s in cat.SIGS:
                    out.append({"arch": a, "sig": s, "kem": k, "depth": d})
    return out


def card_ops_for(sc):
    if sc["arch"] in ("A", "B"):
        return [("sign", sc["sig"])]
    if sc["arch"] == "C-min":
        return [("decaps", sc["kem"])]
    if sc["arch"] == "C-priv":
        return [("encaps", sc["kem"]), ("decaps", sc["kem"])]
    return []


def reader_cycle_total(sc, reader_ops):
    total = 0
    for (op,) in reader_ops:
        if op == "verify":
            if sc["sig"].startswith("R2-"):
                return None   # no reader figure for round-2 parameter sets
            total += cat.reader_cycles(sc["sig"], "verify")
        else:
            total += cat.reader_cycles(sc["kem"], op)
    return total


# ----------------------------------------------------------------- tests

def check(name, got, want):
    if got != want:
        raise SystemExit("TEST %s FAILED: got %r, want %r" % (name, got, want))
    return {"test": name, "value": str(want), "ok": True}


def run_tests():
    L = Link()
    res = []
    res.append(check("T01 etu", L.etu, F(2, 211875)))
    res.append(check("T02 byte", 9 * L.etu, F(24, 282500)))
    res.append(check("T03 FWT_MAX card", L.fwt_card, F(8192, 211875)))
    res.append(check("T04 dFWT", F(49152, L.fc), F(768, 211875)))
    wc, wr = wtx_parts(L)
    res.append(check("T05 WTX round trip", wc + wr, F(273, 226000)))
    res.append(check("T05 WTX card part", wc, F(4736, L.fc)))
    res.append(check("T06 5-byte C-APDU frame", L.reader_frame(8), 74 * L.etu))
    # T07 classical A depth 2
    ex, _, _ = build("A-classical", depth=2)
    tot, card, reader = fixed_times(ex, L)
    res.append(check("T07 card frames etu", tot.card_frames / L.etu, 7918))
    res.append(check("T07 reader frames etu", tot.reader_frames / L.etu, 752))
    res.append(check("T07 gaps", (tot.picc_gaps, tot.pcd_gaps), (7, 7)))
    res.append(check("T07 card tariff", card, F(1021708, 13560000)))
    res.append(check("T07 reader tariff", reader, F(143716, 13560000)))
    res.append(check("T07 APDU bytes", (tot.card_apdu_bytes, tot.reader_apdu_bytes), (858, 61)))
    # T08 PQ A ML-DSA-44 depth 2
    ex, _, _ = build("A", "ML-DSA-44", depth=2)
    tot = closed_form(ex, L)
    rr = [e for e in ex if e.name.startswith("issuer cert")]
    ic = [e for e in ex if e.name.startswith("ICC cert")]
    res.append(check("T08 fragment", ar.FRAG, 247))
    res.append(check("T08 issuer cert", ar.pq_issuer_cert(cat.SIZES["ML-DSA-44"], "E"), 3753))
    res.append(check("T08 ICC cert", ar.pq_icc_cert(cat.SIZES["ML-DSA-44"], 1312, "E"), 3781))
    res.append(check("T08 records", (len(rr), len(ic)), (16, 16)))
    res.append(check("T08 last records", (rr[-1].r_len - 2, ic[-1].r_len - 2), (53, 81)))
    gen = [e for e in ex if e.name.startswith("GENERATE AC") or e.name.startswith("GET RESPONSE")]
    res.append(check("T08 GENERATE AC pieces", len(gen), 10))
    res.append(check("T08 GENERATE AC data", sum(e.r_len - 2 for e in gen), 2438))
    res.append(check("T08 APDU bytes", (tot.card_apdu_bytes, tot.reader_apdu_bytes), (10283, 256)))
    # T09
    tc = F(7925955, 24_000_000)
    n = wtx_count(tc, L.fwt_card)
    res.append(check("T09 WTX count", n, 8))
    res.append(check("T09 WTX added", n * (wc + wr), F(131040, 13560000)))
    # T10 IDEMIA
    Z = cat.SIZES
    k = Z["ML-KEM-512"]
    it = cat.LIT["idemia_table2"]
    def idm(pk, sig):
        return pk + sig + k["ek"] + sig + k["dk"]
    res.append(check("T10 Falcon-512", idm(Z["FN-DSA-512"]["pk"], Z["FN-DSA-512"]["sig"]), it["Falcon-512"]))
    res.append(check("T10 Falcon-1024", idm(Z["FN-DSA-1024"]["pk"], Z["FN-DSA-1024"]["sig"]), it["Falcon-1024"]))
    res.append(check("T10 Dilithium-2", idm(Z["ML-DSA-44"]["pk"], Z["ML-DSA-44"]["sig"]), it["Dilithium-2"]))
    r3 = cat.LIT["round3_sig_sizes"]["Dilithium3"]
    res.append(check("T10 Dilithium-3 (round 3)", idm(Z["ML-DSA-65"]["pk"], r3), it["Dilithium-3"]))
    res.append(check("T10 header bytes", 21 + 17 + 32, 70))
    # T11 RAM
    res.append(check("T11 P26 FN-DSA-512", 20 * 512 + 992 + 666 + MSG + APDU_BUF, 12191))
    st = cat.PQM4["stack_bytes"]
    res.append(check("T11 ML-KEM-512 m4fstack", st["ml-kem-512/m4fstack"]["decaps"] + 768 + SS + APDU_BUF, 3393))
    res.append(check("T11 ML-DSA-44 clean", st["ml-dsa-44/clean"]["sign"] + 2420 + MSG + APDU_BUF, 54689))
    return res


# ---------------------------------------------------------- transcription

def verify_transcription():
    """If pqm4 and pqm3 are cloned into sources/, re-read their benchmark
    tables and make sure data/bench_pqm4.json and bench_pqm3.json still match."""
    if not (os.path.isdir(os.path.join(ROOT, "sources", "pqm4")) and os.path.isdir(os.path.join(ROOT, "sources", "pqm3"))):
        return "skipped (sources/ not cloned)"
    before = {n: open(os.path.join(ROOT, "data", n), encoding="utf-8").read()
              for n in ("bench_pqm4.json", "bench_pqm3.json")}
    subprocess.run([sys.executable, os.path.join(ROOT, "data", "refresh", "read_benchmarks.py")],
                   check=True, capture_output=True)
    for n, t in before.items():
        if open(os.path.join(ROOT, "data", n), encoding="utf-8").read() != t:
            raise SystemExit("transcription mismatch: " + n)
    return "pqm4 and pqm3 tables re-read: identical"


# ------------------------------------------------------------------ main

def ram_required(impl, sc_op_extra=0):
    if impl["work_ram"] is None:
        return None
    s = cat.SIZES[impl["scheme"]]
    if impl["op"] == "sign":
        buf = s["sig"] + MSG
    elif impl["op"] == "decaps":
        buf = s["ct"] + SS
    else:
        buf = s["ek"] + s["ct"] + SS
    return impl["work_ram"] + buf + APDU_BUF


def main():
    check_note = verify_transcription()
    out = {"tests": run_tests()}
    L = Link()
    impls = cat.card_impls()
    chips = cat.chips()

    # ---------------- transport times for every scenario
    rows = []
    for sc in scenarios():
        ex, card_ops, reader_ops = build(sc["arch"], sc["sig"], sc["kem"], sc["depth"])
        tot, card0, reader0 = fixed_times(ex, L)
        row = dict(sc)
        row.update({
            "exchanges": tot.exchanges,
            "card_apdu_bytes": tot.card_apdu_bytes, "reader_apdu_bytes": tot.reader_apdu_bytes,
            "card_link_bytes": tot.card_link_bytes, "reader_link_bytes": tot.reader_link_bytes,
            "card_tx_ms": ms(tot.card_frames), "reader_tx_ms": ms(tot.reader_frames),
            "card_fixed_ms": ms(card0), "reader_fixed_ms": ms(reader0),
            "card_fixed": frac(card0), "reader_fixed": frac(reader0),
            "card_fixed_exceeds_400": card0 >= CARD_BUDGET,
            "reader_fixed_exceeds_100": reader0 >= READER_BUDGET,
            "field_fixed_ms": ms(card0 + reader0),
            "field_fixed_exceeds_500": card0 + reader0 >= FIELD_BUDGET,
        })
        if sc["arch"] not in ("A-classical", "B-classical", "C-classical"):
            rc = reader_cycle_total(sc, reader_ops)
            row["reader_cycles_m4"] = rc
            row["reader_clock_needed_mhz_m4"] = (None if rc is None else
                                                 (None if reader_clock(reader0, rc) is None else mhz(reader_clock(reader0, rc))))
            # sensitivities on the fixed part
            sens = {}
            for label, kw, lk in [
                ("depth-alt", None, None),
                ("format D-C1b", {"fmt": "B2"}, None),
                ("extended APDU D-R2", {"extended": True}, None),
                ("FSD/FSC 1024 + extended", {"extended": True}, {"fsd": 1024, "fsc": 1024}),
                ("FSD/FSC 4096 + extended", {"extended": True}, {"fsd": 4096, "fsc": 4096}),
                ("FSD/FSC 4096, short APDUs", {}, {"fsd": 4096, "fsc": 4096}),
                ("EDC excluded", {}, {"edc_excluded": True}),
                ("FDT_PICC 1236", {}, {"fdt_picc": FDT_PICC_ALT}),
                ("fc 13.553 MHz", {}, {"fc": 13_553_000}),
                ("fc 13.567 MHz", {}, {"fc": 13_567_000}),
                ("D=2 (212 kbit/s, out of spec)", {}, {"divisor": 2}),
                ("D=4 (424 kbit/s, out of spec)", {}, {"divisor": 4}),
                ("D=8 (848 kbit/s, out of spec)", {}, {"divisor": 8}),
            ]:
                if label == "depth-alt":
                    continue
                ex2, _, _ = build(sc["arch"], sc["sig"], sc["kem"], sc["depth"], **kw)
                t2, c2, r2 = fixed_times(ex2, Link(**(lk or {})))
                sens[label] = {"card_fixed_ms": ms(c2), "reader_fixed_ms": ms(r2),
                               "card_apdu_bytes": t2.card_apdu_bytes, "reader_apdu_bytes": t2.reader_apdu_bytes}
            # D-T1b: gaps assigned to neither tariff
            sens["gaps unassigned (D-T1b)"] = {"card_fixed_ms": ms(tot.card_frames),
                                               "reader_fixed_ms": ms(tot.reader_frames)}
            row["sensitivity"] = sens
        rows.append(row)
    out["transport"] = rows

    # ---------------- card computation, clocks, waiting-time extensions
    comp = []
    for sc in scenarios():
        ops = card_ops_for(sc)
        if not ops:
            continue
        ex, _, reader_ops = build(sc["arch"], sc["sig"], sc["kem"], sc["depth"])
        tot = closed_form(ex, L)
        # candidate implementation sets: same id for every op of this scenario
        ids = sorted({i["id"] for i in impls})
        for iid in ids:
            chosen = {}
            for op, scheme in ops:
                m = [i for i in impls if i["id"] == iid and i["scheme"] == scheme and i["op"] == op]
                if m:
                    chosen[(op,)] = m[0]
            if len(chosen) != len(ops):
                continue
            first = next(iter(chosen.values()))
            cycles = {k: v["cycles"] for k, v in chosen.items()}
            f_req = required_clock(ex, L, cycles, CARD_BUDGET)
            rec = {"arch": sc["arch"], "sig": sc["sig"], "kem": sc["kem"], "depth": sc["depth"],
                   "impl": iid, "measured_on": first["measured_on"],
                   "runs_on": list(first["runs_on"]),
                   "card_cycles": {k[0]: v for k, v in cycles.items()},
                   "required_card_clock_mhz": None if f_req is None else mhz(f_req),
                   "no_clock_fits": f_req is None}
            if f_req is not None:
                _, ev = evaluate(ex, L, cycles, f_req)
                rec["at_required"] = {"card_ms": ms(ev["card"]), "wtx": ev["wtx"],
                                      "reader_fixed_ms": ms(ev["reader"])}
            # comparison with each chip of a stated clock
            chip_eval = {}
            for cname, c in chips.items():
                if c["clock_mhz"] is None or c["class"] is None:
                    chip_eval[cname] = {"verdict": "no clock stated in brief"}
                    continue
                if c["class"] not in rec["runs_on"]:
                    chip_eval[cname] = {"verdict": "cannot run (needs %s instructions)" % "/".join(rec["runs_on"])}
                    continue
                f = c["clock_mhz"] * 1_000_000
                _, ev = evaluate(ex, L, cycles, f)
                _, evc = evaluate(ex, L, cycles, f, pause=False)
                rank = {"M0": 0, "M3": 1, "M4": 2}
                if rec["measured_on"] == c["class"]:
                    basis = "measured on this core class"
                elif rank[rec["measured_on"]] > rank[c["class"]]:
                    basis = "LOWER BOUND: measured on more capable %s" % rec["measured_on"]
                else:
                    basis = "measured on less capable %s; not a measurement on %s" % (rec["measured_on"], c["class"])
                chip_eval[cname] = {
                    "clock_mhz": c["clock_mhz"], "basis": basis,
                    "card_ms": ms(ev["card"]), "fits_400": ev["card"] <= CARD_BUDGET,
                    "wtx": ev["wtx"], "wtx_added_ms": ms(ev["card"] - evc["card"] + ev["reader"] - evc["reader"]),
                    "reader_fixed_ms": ms(ev["reader"]),
                    "field_lower_bound_ms": ms(ev["card"] + ev["reader"]),
                    "fits_500_field": ev["card"] + ev["reader"] <= FIELD_BUDGET,
                }
            rec["chips"] = chip_eval
            comp.append(rec)
    out["computation"] = comp
    out["card_impls"] = [{"id": i["id"], "scheme": i["scheme"], "op": i["op"], "measured_on": i["measured_on"],
                          "runs_on": list(i["runs_on"]), "cycles": i["cycles"], "cycles_max": i["cycles_max"],
                          "source": i["source"], "note": i["note"]} for i in impls]
    out["reader_cycles_m4"] = {s + " " + op: cat.reader_cycles(s, op)
                               for s in cat.SIGS for op in ("verify",)}
    out["reader_cycles_m4"].update({k + " " + op: cat.reader_cycles(k, op)
                                    for k in cat.KEMS for op in ("keygen", "encaps", "decaps")})

    # ---------------- S(WTX) per card computation at the chips' clocks
    wc, wr = wtx_parts(L)
    wtx_rows = []
    for i in impls:
        for cname, c in chips.items():
            if c["clock_mhz"] is None or c["class"] not in i["runs_on"]:
                continue
            tc = F(i["cycles"], c["clock_mhz"] * 1_000_000)
            n = wtx_count(tc, L.fwt_card)
            wtx_rows.append({"impl": i["id"], "scheme": i["scheme"], "op": i["op"],
                             "measured_on": i["measured_on"], "chip": cname,
                             "clock_mhz": c["clock_mhz"], "compute_ms": ms(tc), "wtx": n,
                             "added_ms_pause": ms(n * (wc + wr)),
                             "added_ms_card": ms(n * wc), "added_ms_reader": ms(n * wr)})
    out["wtx"] = {"round_trip_ms": ms(wc + wr, 6), "round_trip": frac(wc + wr),
                  "window_ms": ms(L.fwt_card, 6), "rows": wtx_rows}

    # ---------------- RAM
    ram_rows = []
    for i in impls:
        req = ram_required(i)
        r = {"impl": i["id"], "scheme": i["scheme"], "op": i["op"],
             "measured_on": i["measured_on"], "runs_on": list(i["runs_on"]),
             "work_ram": None if i["work_ram"] is None else str(i["work_ram"]),
             "required_bytes": None if req is None else str(req)}
        if req is not None:
            r["fits_kb1024"] = {str(k): req <= k * KB for k in RAM_SIZES}
            r["fits_kb1000"] = {str(k): req <= k * 1000 for k in RAM_SIZES}
            sk = cat.SIZES[i["scheme"]].get("sk") or cat.SIZES[i["scheme"]].get("dk")
            if sk:
                r["required_with_sk_in_ram"] = str(req + sk)
        ram_rows.append(r)
    # Precomputed-key Falcon (P19) and PQ-EAC data point
    p19 = cat.LIT["pornin2019_m4"]["FN-DSA-512"]
    ram_rows.append({"impl": "Pornin 2019 expanded-key signing", "scheme": "FN-DSA-512", "op": "sign",
                     "measured_on": "M4", "runs_on": ["M4"],
                     "work_ram": str(p19["tree_sign_temp_bytes"]),
                     "required_bytes": str(p19["tree_sign_temp_bytes"] + 666 + MSG + APDU_BUF),
                     "expanded_key_bytes": p19["expanded_key_bytes"],
                     "fits_kb1024": {str(k): p19["tree_sign_temp_bytes"] + 666 + MSG + APDU_BUF <= k * KB for k in RAM_SIZES}})
    out["ram"] = ram_rows

    # ---------------- computation sensitivities
    sens = []
    for s in cat.SIGS:
        base = [i for i in impls if i["scheme"] == s and i["op"] == "sign"]
        for i in base:
            if i["cycles_max"]:
                sens.append({"what": "tail (observed MAX)", "scheme": s, "impl": i["id"],
                             "mean": i["cycles"], "max": i["cycles_max"]})
    m = cat.LIT["masking"]
    for s in ["ML-DSA-44", "ML-DSA-65", "ML-DSA-87"]:
        b = next(i for i in impls if i["scheme"] == s and i["id"] == "pqm4 m4f")
        sens.append({"what": "2-share masking (AZ22), applied to pqm4 m4f", "scheme": s,
                     "randomized": str(F(m["mldsa_sign_2share_randomized"]) * b["cycles"]),
                     "deterministic": str(F(m["mldsa_sign_2share_deterministic"]) * b["cycles"])})
    p19 = cat.LIT["pornin2019_m4"]
    for s in ("FN-DSA-512", "FN-DSA-1024"):
        sens.append({"what": "Falcon expanded-key (precomputed) signing, P19 (168 MHz, caches)",
                     "scheme": s, "sign_dynamic": p19[s]["sign_dynamic"], "sign_tree": p19[s]["sign_tree"],
                     "expand_key_once": p19[s]["expand_key"], "expanded_key_bytes": p19[s]["expanded_key_bytes"]})
    out["compute_sensitivity"] = sens

    # required clocks for best-published pairs and masked ML-DSA, arch A/B depth 2
    best = []
    for a in ("A", "B"):
        for s in cat.SIGS:
            ex, _, _ = build(a, s, None, 2)
            for label, cyc in [
                ("best published M4", next(i["cycles"] for i in impls if i["scheme"] == s and i["op"] == "sign" and
                                            i["id"] == ("Huang (round 3)" if s.startswith("ML") else "Pornin 2026 RAM-efficient"))),
                ("pqm4 m4f", next(i["cycles"] for i in impls if i["scheme"] == s and i["op"] == "sign" and i["id"] == "pqm4 m4f")),
            ] + ([("pqm4 m4f x 2-share masking (randomized)", F(m["mldsa_sign_2share_randomized"]) * next(
                    i["cycles"] for i in impls if i["scheme"] == s and i["op"] == "sign" and i["id"] == "pqm4 m4f"))]
                  if s.startswith("ML") else []) + (
                 [("P19 expanded-key signing", p19[s]["sign_tree"])] if s.startswith("FN") else []):
                f = required_clock(ex, L, {("sign",): cyc}, CARD_BUDGET)
                best.append({"arch": a, "sig": s, "variant": label, "cycles": str(cyc),
                             "required_card_clock_mhz": None if f is None else mhz(f)})
    for a in ("C-min", "C-priv"):
        for k in cat.KEMS:
            ex, _, _ = build(a, "FN-DSA-512", k, 2)
            hm = cat.LIT["huang_m4"][cat.HUANG_NAME[k]]
            ops = {"C-min": {("decaps",): hm["decaps_kc"] * 1000},
                   "C-priv": {("encaps",): hm["encaps_kc"] * 1000, ("decaps",): hm["decaps_kc"] * 1000}}[a]
            f = required_clock(ex, L, ops, CARD_BUDGET)
            mm = {kk: v * cat.LIT["masking"]["kem_countermeasure_upper"] for kk, v in ops.items()}
            f2 = required_clock(ex, L, mm, CARD_BUDGET)
            best.append({"arch": a, "sig": "FN-DSA-512", "kem": k, "variant": "best published M4 (Huang Kyber)",
                         "required_card_clock_mhz": None if f is None else mhz(f),
                         "x2 countermeasures (IDEMIA upper)": None if f2 is None else mhz(f2)})
    out["best_published_and_hardening"] = best

    # ---------------- E: same portable code measured on three core classes
    ev = []
    for s, n3, op in [("ML-DSA-44", "dilithium2", "sign"), ("ML-DSA-65", "dilithium3", "sign"),
                      ("ML-KEM-512", "kyber512", "decaps"), ("ML-KEM-768", "kyber768", "decaps"),
                      ("ML-KEM-1024", "kyber1024", "decaps"), ("ML-KEM-512", "kyber512", "encaps")]:
        m4 = cat.PQM4["speed_cycles"][cat.PQM4_NAME[s] + "/clean"][op]["avg"]
        m3 = cat.PQM3["speed_cycles"][n3 + "/clean"][op]["avg"]
        m0 = cat.LIT["m0plus"][s][op + "_kc"] * 1000
        ev.append({"scheme": s, "op": op, "pqm4_clean_M4_FIPS": m4, "pqm3_clean_M3_round3": m3,
                   "M0plus_PQClean_FIPS": m0, "M3_over_M4": str(F(m3, m4)), "M0_over_M4": str(F(m0, m4)),
                   "M3_gt_M4": m3 > m4, "M0_gt_M3": m0 > m3})
    out["core_evidence"] = ev

    # ---------------- IDEMIA consistency check
    Z = cat.SIZES
    k = Z["ML-KEM-512"]
    q9 = []
    for name, pk, sig in [("Falcon-512", Z["FN-DSA-512"]["pk"], Z["FN-DSA-512"]["sig"]),
                          ("Falcon-1024", Z["FN-DSA-1024"]["pk"], Z["FN-DSA-1024"]["sig"]),
                          ("Dilithium-2", Z["ML-DSA-44"]["pk"], Z["ML-DSA-44"]["sig"]),
                          ("Dilithium-3", Z["ML-DSA-65"]["pk"], cat.LIT["round3_sig_sizes"]["Dilithium3"])]:
        ours = (21 + pk + sig) + (17 + 32 + k["ek"] + sig) + k["dk"]
        q9.append({"sig": name, "idemia_theoretical": cat.LIT["idemia_table2"][name],
                   "keys_and_sigs": pk + sig + k["ek"] + sig + k["dk"], "ours_with_headers": ours,
                   "difference": ours - cat.LIT["idemia_table2"][name]})
    out["idemia"] = q9

    print("benchmark tables: " + check_note)
    save_or_check(out, os.path.join(ROOT, "results", "results.json"))
    print("tests: %d passed; transport rows %d; computation rows %d; RAM rows %d"
          % (len(out["tests"]), len(rows), len(comp), len(ram_rows)))
    run_analyses()


def save_or_check(out, path):
    """Write results.json with --write; otherwise it must equal the committed file."""
    text = json.dumps(out, indent=1, sort_keys=True, default=str) + "\n"
    if "--write" in sys.argv:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        return
    if not os.path.exists(path) or open(path, encoding="utf-8").read() != text:
        raise SystemExit("results/results.json differs from a fresh run (use --write to update it)")


def run_analyses():
    """Run the analyses (they rewrite their JSON in results/), the hand check
    of the Kernel 8 remainder, and the checks that the paper's numbers and
    figure data regenerate exactly."""
    for name in ("fit_matrix", "kernel8_rest", "kernel8_rmin", "ram_4500", "protected_mlkem", "figure_data"):
        subprocess.run([sys.executable, os.path.join(ROOT, "analyses", name + ".py")], check=True, capture_output=True)
    check = [] if "--write" in sys.argv else ["--check"]
    for script, args in (("tests/test_rmin_by_hand.py", []), ("paper/make_numbers.py", check),
                         ("paper/make_figures.py", check)):
        r = subprocess.run([sys.executable, os.path.join(ROOT, script)] + args, capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit("%s failed:\n%s%s" % (script, r.stdout, r.stderr))
        print(r.stdout.strip())


if __name__ == "__main__":
    main()
