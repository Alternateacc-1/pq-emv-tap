"""Card and reader implementations: cycles, stack and the cores each can run on
(choices D-W3, D-M1 and D-R3 in docs/modelling_choices.md).

Each card implementation entry:
  id, scheme, op, measured_on (core class), runs_on (core classes whose ISA
  the code needs), cycles (mean), cycles_max, work_ram (stack/work bytes as
  published, Fraction), source.
"""
import json
import os
from fractions import Fraction as F

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def load(name):
    with open(os.path.join(ROOT, "data", name), encoding="utf-8") as f:
        return json.load(f)


LIT = load("literature.json")
PQM4 = load("bench_pqm4.json")
PQM3 = load("bench_pqm3.json")
ISA = load("pqm4_isa_scan.json")

SIZES = {k: v for k, v in LIT["sizes"].items() if not k.startswith("_")}
SIGS = ["ML-DSA-44", "ML-DSA-65", "ML-DSA-87", "FN-DSA-512", "FN-DSA-1024"]
R2SIGS = ["R2-Dilithium2", "R2-Dilithium3", "R2-Dilithium4"]
KEMS = ["ML-KEM-512", "ML-KEM-768", "ML-KEM-1024"]

PQM4_NAME = {"ML-DSA-44": "ml-dsa-44", "ML-DSA-65": "ml-dsa-65", "ML-DSA-87": "ml-dsa-87",
             "FN-DSA-512": "fndsa_provisional-512", "FN-DSA-1024": "fndsa_provisional-1024",
             "ML-KEM-512": "ml-kem-512", "ML-KEM-768": "ml-kem-768", "ML-KEM-1024": "ml-kem-1024"}
PQM3_NAME = {"ML-DSA-44": "dilithium2", "ML-DSA-65": "dilithium3",
             "ML-KEM-512": "kyber512", "ML-KEM-768": "kyber768", "ML-KEM-1024": "kyber1024"}
HUANG_NAME = {"ML-DSA-44": "Dilithium2", "ML-DSA-65": "Dilithium3", "ML-DSA-87": "Dilithium5",
              "ML-KEM-512": "Kyber512", "ML-KEM-768": "Kyber768", "ML-KEM-1024": "Kyber1024"}

ALL = ("M4", "M3", "M0")


def runs_on_pqm4(scheme_dir, variant):
    scan = ISA.get("%s/%s" % (scheme_dir, variant))
    if variant == "clean":
        return ALL
    if scan is None:
        raise KeyError((scheme_dir, variant))
    if sum(scan["dsp"].values()) or sum(scan["fpu"].values()):
        return ("M4",)
    return ALL


def card_impls():
    out = []

    def add(**kw):
        kw.setdefault("cycles_max", None)
        kw.setdefault("note", "")
        out.append(kw)

    # --- Cortex-M4: pqm4
    for s in SIGS + KEMS:
        d = PQM4_NAME[s]
        is_sig = s in SIGS
        variants = (["clean", "m4f", "m4fstack"] if s.startswith("ML-DSA") else
                    ["ref", "m4f"] if s.startswith("FN-DSA") else
                    ["clean", "m4fspeed", "m4fstack"])
        for v in variants:
            key = "%s/%s" % (d, v)
            sp, st = PQM4["speed_cycles"][key], PQM4["stack_bytes"][key]
            ops = ["sign"] if is_sig else ["encaps", "decaps"]
            if v == "ref":
                ro = ALL   # the ref code is portable C: FNDSA_ASM_CORTEXM4 defaults to 0 (D-W3)
            else:
                ro = runs_on_pqm4(d, v)
            for op in ops:
                add(id="pqm4 %s" % v, scheme=s, op=op, measured_on="M4", runs_on=ro,
                    cycles=sp[op]["avg"], cycles_max=sp[op]["max"], work_ram=F(st[op]),
                    source="PQM4 benchmarks.md (%s)" % key)
    # --- Cortex-M4: literature
    hm = LIT["huang_m4"]
    for s, n in HUANG_NAME.items():
        for op in (["sign"] if s in SIGS else ["encaps", "decaps"]):
            add(id="Huang (round 3)", scheme=s, op=op, measured_on="M4", runs_on=("M4",),
                cycles=hm[n][op + "_kc"] * 1000, work_ram=None,
                source="HUANG Table 6 (%s)" % n)
    p26 = LIT["pornin2026_m4"]
    for s in ("FN-DSA-512", "FN-DSA-1024"):
        n = p26[s]["n"]
        add(id="Pornin 2026 RAM-efficient", scheme=s, op="sign", measured_on="M4",
            runs_on=("M4",), cycles=p26[s]["sign_new"],
            work_ram=F(p26["temp_per_n_new"] * n + p26["stack_new"]),
            source="P26 Table 1 and p.33",
            note="portable C build exists (c-fn-dsa-alt Makefile); only the M4 assembly build is measured")
        p25 = LIT["pornin2025_m4"][s]
        add(id="Pornin 2025", scheme=s, op="sign", measured_on="M4", runs_on=("M4",),
            cycles=p25["sign"], work_ram=F(sum(p25["sign_ram"])), source="P25 Table 1")
    # --- Cortex-M3: pqm3
    for s, n in PQM3_NAME.items():
        for v in ("clean", "m3"):
            key = "%s/%s" % (n, v)
            sp, st = PQM3["speed_cycles"][key], PQM3["stack_bytes"][key]
            for op in (["sign"] if s in SIGS else ["encaps", "decaps"]):
                add(id="pqm3 %s" % v, scheme=s, op=op, measured_on="M3",
                    runs_on=ALL if v == "clean" else ("M4", "M3"),
                    cycles=sp[op]["avg"], cycles_max=sp[op]["max"], work_ram=F(st[op]),
                    source="PQM3 benchmarks-nucleo-f207zg.md (%s), round 3" % key)
    # --- Cortex-M3: GKS21 round-2 Dilithium (own parameter sets)
    g = LIT["gks21_m3"]
    for s in R2SIGS:
        for strat in (1, 2, 3):
            add(id="GKS21 strategy %d" % strat, scheme=s, op="sign", measured_on="M3",
                runs_on=("M4", "M3"), cycles=g[s]["sign%d_kc" % strat] * 1000,
                work_ram=F(g[s]["sign%d_stack" % strat]),
                source="GKS21 Table 4, round 2")
    # --- Cortex-M0+: M0P
    m0 = LIT["m0plus"]
    for s in ["ML-DSA-44", "ML-DSA-65", "ML-DSA-87"] + KEMS:
        for op in (["sign"] if s in SIGS else ["encaps", "decaps"]):
            key = op + "_stack_kb"
            wr = F(m0[s][key]) * 1024 if key in m0[s] else None
            add(id="M0+ PQClean", scheme=s, op=op, measured_on="M0", runs_on=ALL,
                cycles=m0[s][op + "_kc"] * 1000, work_ram=wr,
                source="M0P Tables IV/V/IX (cycles derived as t x 125 MHz)")
    return out


def reader_cycles(scheme, op):
    """D-R3: Cortex-M4 pqm4 m4f / m4fspeed."""
    d = PQM4_NAME[scheme]
    v = "m4fspeed" if scheme.startswith("ML-KEM") else "m4f"
    return PQM4["speed_cycles"]["%s/%s" % (d, v)][op]["avg"]


def chips():
    return {k: v for k, v in LIT["chips"].items() if not k.startswith("_")}
