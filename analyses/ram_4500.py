"""RAM at the one measured figure for RAM available to cryptography (correction E5).

Alnahawi et al. (ePrint 2025/812) report about 4.5 kB of RAM free for
cryptography on an NXP SmartMX3 card running Java Card. Every RAM row of
results/results.json is checked against 4500 and 4608 bytes.

Writes results/ram_4500.json (and a readable results/ram_4500.md).
"""
import json
import os
from fractions import Fraction as F

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIMITS = {"4500": 4500, "4608": 4608}
PAYMENT_CORES = ("M3", "M0")      # SC300 (M3-class), SC000 (M0-based)

# card-side operation each architecture needs (DECISIONS D-C1..D-C4)
ARCH_OPS = {
    "A / B (card signs)": ["sign"],
    "C-min (card decapsulates)": ["decaps"],
    "C-priv (card encapsulates and decapsulates)": ["encaps", "decaps"],
}


def main():
    ram = json.load(open(os.path.join(ROOT, "results", "results.json"), encoding="utf-8"))["ram"]
    rows = []
    for x in ram:
        rb = x.get("required_bytes")
        req = F(rb) if rb is not None else None
        on_pay = any(c in x["runs_on"] for c in PAYMENT_CORES)
        fits = {k: (req is not None and req <= v) for k, v in LIMITS.items()}
        fits16 = x.get("fits_kb1024", {}).get("16", False)
        rows.append({"scheme": x["scheme"], "op": x["op"], "impl": x["impl"],
                     "runs_on": x["runs_on"], "payment_core_executable": on_pay,
                     "required_bytes": rb, "fits_16kb_brief": fits16,
                     "fits_4500": fits["4500"], "fits_4608": fits["4608"]})
    fit_any = [r for r in rows if r["fits_4608"]]
    fit_pay = [r for r in fit_any if r["payment_core_executable"]]
    lost = [r for r in rows if r["payment_core_executable"] and r["fits_16kb_brief"] and not r["fits_4500"]]
    arch = {}
    for a, ops in ARCH_OPS.items():
        ok = {}
        for op in ops:
            ok[op] = sorted({"%s %s" % (r["scheme"], r["impl"]) for r in fit_pay if r["op"] == op and r["fits_4500"]})
        arch[a] = ok
    out = {"limits_bytes": LIMITS, "rows": len(rows),
           "fit_4608_any_core": [(r["scheme"], r["op"], r["impl"], r["required_bytes"]) for r in fit_any],
           "fit_4500_payment_core": [(r["scheme"], r["op"], r["impl"], r["required_bytes"])
                                     for r in fit_pay if r["fits_4500"]],
           "fit_4608_payment_core": [(r["scheme"], r["op"], r["impl"], r["required_bytes"]) for r in fit_pay],
           "lost_vs_16kb_brief": [(r["scheme"], r["op"], r["impl"], r["required_bytes"]) for r in lost],
           "by_architecture_4500": arch}
    with open(os.path.join(ROOT, "results", "ram_4500.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
        fh.write("\n")
    md = ["| scheme | op | implementation | runs on | required B (D-M1) | fits 16 KB brief | fits 4 500 B | fits 4 608 B |",
          "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if r["required_bytes"] is None:
            continue
        md.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["scheme"], r["op"], r["impl"], ", ".join(r["runs_on"]), r["required_bytes"],
            "yes" if r["fits_16kb_brief"] else "no", "yes" if r["fits_4500"] else "no",
            "yes" if r["fits_4608"] else "no"))
    with open(os.path.join(ROOT, "results", "ram_4500.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(md) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))


if __name__ == "__main__":
    main()
