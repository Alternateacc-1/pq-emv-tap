"""Protected (side-channel hardened) ML-KEM on the card (correction E6).

1. The largest ML-KEM-512 decapsulation cost, in cycles, that keeps C-min
   within the card's 400 ms on each payment chip's clock.
2. The only published Cortex-M3 figure for protected ML-KEM (Bettale, Dottax
   and Gremy, SECRYPT 2025): the extra processing of the hybrid mode at
   100 MHz, attributed to one key generation and two decapsulations. If key
   generation costs no more than a decapsulation, one decapsulation costs
   between a third and a half of that increment.

Writes results/protected_mlkem.json.
"""
import json
import os
import sys
from fractions import Fraction as F

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

def need(cond, what):
    """Stop with a message when a check fails (works under python -O too)."""
    if not cond:
        raise SystemExit("check failed: %r" % (what,))

sys.path.insert(0, ROOT)

import run as R                                        # noqa: E402
from pqemv.transport import Link, evaluate_closed      # noqa: E402

CHIP_CLOCKS = [("SC300 (Infineon SLC36/37PDx)", 80_000_000), ("SC000 (ST31N600)", 60_000_000),
               ("SC000 (ST31P450)", 55_000_000)]


def decaps_budget(f):
    ex, cops, _ = R.build("C-min", "FN-DSA-512", "ML-KEM-512", 2)
    need(cops == [("decaps",)], "check failed")
    link = Link()
    tot, _, _ = R.fixed_times(ex, link)

    def ok(c):
        return evaluate_closed(tot, link, {("decaps",): F(c, f)}, True)["card"] <= R.CARD_BUDGET
    lo, hi = 0, 10 ** 9
    while lo < hi:
        mid = (lo + hi + 1) // 2
        lo, hi = (mid, hi) if ok(mid) else (lo, mid - 1)
    return lo


def main():
    lit = json.load(open(os.path.join(ROOT, "data", "literature_extra.json"), encoding="utf-8"))["bdg25"]
    res = json.load(open(os.path.join(ROOT, "results", "results.json"), encoding="utf-8"))
    unprot = [x for x in res["card_impls"] if x["id"] == "pqm3 m3" and x["scheme"] == "ML-KEM-512" and x["op"] == "decaps"][0]
    inc_ms = lit["mode_b_128_hybrid_processing_ms"] - lit["mode_b_128_classic_processing_ms"]
    inc_cyc = F(inc_ms, 1000) * lit["clock_hz"]
    ops = lit["pq_ops_mode_b"]
    lo = inc_cyc / (ops["keygen"] + ops["decaps"])        # KeyGen = Decaps
    hi = inc_cyc / ops["decaps"]                          # KeyGen ~ 0
    budgets = []
    for chip, f in CHIP_CLOCKS:
        b = decaps_budget(f)
        verdict = ("fits even at the upper bound" if b >= hi else
                   "UNRESOLVED (budget inside the bracket)" if b >= lo else
                   "exceeds even at the lower bound")
        budgets.append({"chip": chip, "clock_hz": f, "budget_cycles": b, "verdict_vs_bracket": verdict})
    out = {"config": {"arch": "C-min", "sig": "FN-DSA-512", "kem": "ML-KEM-512", "depth": 2, "fsd_fsc": 256},
           "bdg25_increment_ms": inc_ms, "bdg25_increment_cycles": R.frac(inc_cyc),
           "decaps_lo_cycles": R.frac(lo), "decaps_hi_cycles": R.frac(hi),
           "unprotected_pqm3_m3_decaps_cycles": unprot["cycles"],
           "ratio_lo": R.frac(lo / unprot["cycles"]), "ratio_hi": R.frac(hi / unprot["cycles"]),
           "sealed_margin_sc300": R.frac(F(80_000_000) / 5_656_000), "budgets": budgets}
    with open(os.path.join(ROOT, "results", "protected_mlkem.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
