"""Number pipeline: every number printed in the paper, as a LaTeX macro.

Generates paper/numbers.tex (LaTeX \\newcommand macros) and
paper/numbers_manifest.csv from results/results.json, the analysis outputs in results/,
the model (for quantities the JSONs store only rounded) and the
transcription files in data/. No value is typed here: every macro is computed
by a function below from one of those artifacts. The manifest's erratum
column names the correction (E1-E7) behind a value where there is one.

Rounding rules (declared once; the manifest names the rule per macro):
  ms1      milliseconds, 1 decimal, half up (text)
  ms3      milliseconds, 3 decimals, half up (tables)
  lb1      lower bound for a ">=" statement: milliseconds, 1 decimal, rounded
           down, so the printed bound never exceeds the exact value (the only
           non-half-up rule; used only where the text says ">=")
  ms0x     milliseconds that are exact integers (asserted; no rounding)
  mhz1     MHz, 1 decimal, half up;   mhz0x: MHz exact integers (asserted)
  ghz1     GHz, 1 decimal, half up
  mhz3     MHz, 3 decimals, half up
  mcyc1/mcyc2  millions of cycles, 1/2 decimals, half up
  x1/x2    ratio, 1/2 decimals, half up
  us0      microseconds, integer, half up
  kb1      kilobytes (1000 B), 1 decimal, half up
  exact    bytes, cycles, counts, Hz: exact integer
  pub      transcribed as published (string copied from the source)

Usage: python paper/make_numbers.py            (write)
       python paper/make_numbers.py --check    (regenerate in memory; fail on any diff)
"""
import csv
import io
import json
import os
import re
import sys
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN
from fractions import Fraction as F

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

import run as R                                                  # noqa: E402
from pqemv import implementations as cat                               # noqa: E402
from pqemv import architectures as ar                            # noqa: E402
from pqemv.transport import Link, closed_form, evaluate_closed   # noqa: E402

FC = 13_560_000
GAP = F(6780, FC)                 # FDT_A,PCD,MIN (correction E3 for architecture A)

def need(cond, what):
    """Stop with a message when a check fails (works under python -O too)."""
    if not cond:
        raise SystemExit("check failed: %r" % (what,))



def J(name):
    return json.load(open(os.path.join(ROOT, name), encoding="utf-8"))


RES = J("results/results.json")
FIT = J("results/fit_matrix.json")
REST = J("results/kernel8_rest.json")
RMIN = J("results/kernel8_rmin.json")
RAM45 = J("results/ram_4500.json")
LIT_EXTRA = J("data/literature_extra.json")


# ---------------------------------------------------------------- rounding

def _dec(x):
    if isinstance(x, F):
        return Decimal(x.numerator) / Decimal(x.denominator)
    return Decimal(str(x))


def rnd(x, nd, mode=ROUND_HALF_UP):
    d = _dec(x)
    q = Decimal(1).scaleb(-nd)
    s = abs(d).quantize(q, rounding=mode)
    return ("-" if d < 0 and s != 0 else "") + format(s, "f")


def _int(v):
    """Exact integer only: asserts that no rounding happens."""
    v = F(v)
    need(v.denominator == 1, v)
    return str(v.numerator)


RULES = {
    "ms1": lambda s: rnd(s * 1000, 1), "ms3": lambda s: rnd(s * 1000, 3),
    "ms0x": lambda s: _int(s * 1000), "lb1": lambda s: rnd(s * 1000, 1, ROUND_DOWN),
    "mhz1": lambda hz: rnd(F(hz) / 10**6, 1), "mhz3": lambda hz: rnd(F(hz) / 10**6, 3), "mhz0x": lambda hz: _int(F(hz) / 10**6),
    "ghz1": lambda hz: rnd(F(hz) / 10**9, 1),
    "mcyc1": lambda c: rnd(F(c) / 10**6, 1), "mcyc2": lambda c: rnd(F(c) / 10**6, 2),
    "x1": lambda r: rnd(r, 1), "x2": lambda r: rnd(r, 2), "us0": lambda s: rnd(s * 10**6, 0),
    "kb1": lambda b: rnd(F(b) / 1000, 1), "exact": lambda v: str(v), "pub": lambda v: str(v),
}


def group(s):
    """Thousands grouping with a space (only >= 10 000), as in the paper."""
    neg = s.startswith("-")
    s = s.lstrip("-")
    ip, _, fp = s.partition(".")
    if len(ip) > 4:
        ip = " ".join([ip[max(0, i - 3):i] for i in range(len(ip), 0, -3)][::-1])
    return ("-" if neg else "") + ip + ("." + fp if fp else "")


MACROS = []




def add(name, exact, rule, units, producer, source, erratum="", group_digits=True):
    need(re.fullmatch(r"[A-Za-z]+", name), name)
    need(name not in {m["macro"] for m in MACROS}, name)
    printed = RULES[rule](exact)
    if group_digits:
        printed = group(printed)
    MACROS.append({"macro": name, "printed": printed,
                   "exact": str(exact) if not isinstance(exact, F) else "%s/%s" % (exact.numerator, exact.denominator)
                   if exact.denominator != 1 else str(exact.numerator),
                   "units": units, "rule": rule, "producer": producer, "source": source, "erratum": erratum})


def rows(arch=None, sig=None, kem=None, depth=2):
    out = [t for t in RES["transport"] if t["depth"] == depth and (arch is None or t["arch"] == arch)
           and (sig is None or t["sig"] == sig) and (kem is None or t["kem"] == kem)]
    return out


def one(**kw):
    r = rows(**kw)
    need(len(r) == 1, (kw, len(r)))
    return r[0]


def reader_fixed(t):
    """Reader-fixed time, with erratum E3 applied to architecture A."""
    v = F(t["reader_fixed"])
    return v - GAP if t["arch"] in ("A", "A-classical") else v


def field_fixed(t):
    v = F(t["card_fixed"]) + F(t["reader_fixed"])
    return v - GAP if t["arch"] in ("A", "A-classical") else v


# ---------------------------------------------------------------- registry

def build():
    MACROS.clear()
    P = "paper/make_numbers.py:build"

    # ---- budgets and link constants (run.py / pqemv.transport; L1 and Book A)
    add("ReaderTariffMs", R.READER_BUDGET, "ms0x", "ms", P, "run.py READER_BUDGET (Book A 10.2.1.1)")
    add("CardTariffMs", R.CARD_BUDGET, "ms0x", "ms", P, "run.py CARD_BUDGET (Book A 10.2, implied)")
    add("FieldTargetMs", R.FIELD_BUDGET, "ms0x", "ms", P, "run.py FIELD_BUDGET (Book A 10.1)")
    L = Link()
    add("BitRateKbps", rnd(F(FC, 128) / 1000, 0), "pub", "kbit/s", P, "pqemv.transport Link (fc/128; L1 4.2.1.1)")
    add("BitRateDFourKbps", rnd(F(FC, 32) / 1000, 0), "pub", "kbit/s", P, "Link(divisor=4) (out of EMV)")
    add("ByteCostUs", 9 * L.etu, "us0", "us", P, "TESTS T02 (9 etu)")
    add("FwtCardFc", 4096 * 2 ** 7, "exact", "1/fc", P, "pqemv.transport FWT_CARD (Table A.6 PICC FWI_MAX 7)")
    add("FwtCardMs", L.fwt_card, "ms3", "ms", P, "results.json wtx.window_ms / Link.fwt_card")
    add("CardFwiMax", 7, "exact", "", P, "L1 Table A.6 PICC FWI_MAX")
    add("WtxRoundTripFc", 16380, "exact", "1/fc", P, "TESTS T05")
    add("WtxRoundTripMs", F(RES["wtx"]["round_trip"]), "ms3", "ms", P, "results.json wtx.round_trip")
    add("TpMs", F(RMIN["t_p"]), "ms1", "ms", P, "results/kernel8_rmin.json t_p (L1 Table A.7 PCD min)")
    add("TwoTpMs", 2 * F(RMIN["t_p"]), "ms1", "ms", P, "2 x kernel8_rmin.json t_p")
    add("RespMaxBytes", ar.RESP_MAX, "exact", "B", P, "pqemv.architectures RESP_MAX (Book 1 §11.1.1)")
    add("CmdMaxBytes", ar.CMD_MAX, "exact", "B", P, "pqemv.architectures CMD_MAX (Book 2 D1)")
    add("RecordMaxBytes", ar.RECORD_MAX, "exact", "B", P, "pqemv.architectures RECORD_MAX (Book 3 §7.1)")
    add("CertObjMaxBytes", ar.RSA["NCA"], "exact", "B", P, "C-8 A.1.65/A.1.74; pqemv.architectures RSA NCA")
    add("FsdMinBytes", L.fsd, "exact", "B", P, "Link default FSD (Table A.6 FSDMIN)")
    add("FsFiveTwelve", 512, "exact", "B", P, "results/kernel8_rmin.json applied cfg FSD=FSC", group_digits=False)
    add("FsFourKilo", 4096, "exact", "B", P, "L1 Table 5.14 FSDI 'C'", group_digits=False)

    # ---- sizes (implementations: FIPS 203/204, Falcon v1.2)
    Z = cat.SIZES
    add("FnFiveSigBytes", Z["FN-DSA-512"]["sig"], "exact", "B", P, "implementations SIZES (Falcon v1.2 Table 3.3)")
    add("DilThreeRoundThreeSigBytes", cat.LIT["round3_sig_sizes"]["Dilithium3"], "exact", "B", P,
        "data/literature.json round3_sig_sizes")

    # ---- chips (data/literature.json chips via implementations)
    ch = cat.chips()
    add("ScThreeClockMHz", ch["Infineon SLC37PDx"]["clock_mhz"] * 10**6, "mhz0x", "MHz", P, "chips SLC37PDx (IFX-SLC3x)")
    add("StNSixClockMHz", ch["ST31N600"]["clock_mhz"] * 10**6, "mhz0x", "MHz", P, "chips ST31N600 (ST-N600)")
    add("StPFourClockMHz", ch["ST31P450"]["clock_mhz"] * 10**6, "mhz0x", "MHz", P, "chips ST31P450 (ST-P450)")
    add("SlcThreeSixRamKB", ch["Infineon SLC36PDx"]["ram_kb"], "exact", "KB", P, "chips SLC36PDx")
    add("SlcThreeSevenRamKB", ch["Infineon SLC37PDx"]["ram_kb"], "exact", "KB", P, "chips SLC37PDx")
    add("StNSixRamKB", ch["ST31N600"]["ram_kb"], "exact", "KB", P, "chips ST31N600")
    add("StPFourRamKB", ch["ST31P450"]["ram_kb"], "exact", "KB", P, "chips ST31P450")
    add("NxpRamKB", ch["NXP P71D321 family"]["ram_kb"], "exact", "KB", P, "chips NXP P71D321 family")

    # ---- F2
    dec = [d for d in FIT["fndsa512_decomposition"] if d["arch"] == "A" and d["depth"] == 2]
    add("FnFiveWtxCount", dec[0]["wtx_n"][0], "exact", "", P, "fit_matrix.json fndsa512_decomposition")
    add("FnFiveWtxCardMs", F(dec[0]["wtx_card_ms"]) / 1000, "ms3", "ms", P, "fit_matrix.json (6-dp JSON)")

    # ---- F4 / F5 (fit_matrix c_reader, depth 2, FSD 256)
    cr = [c for c in FIT["c_reader"] if c["depth"] == 2]
    add("CConfigs", len(cr), "exact", "", P, "fit_matrix.json c_reader depth 2")
    add("CTxOnlyExceed", sum(1 for c in cr if c["exceeds_tx_only"]), "exact", "", P, "fit_matrix.json c_reader")
    add("CTxOnlyExceedAllFs", sum(1 for c in cr if c["arch"] == "C-priv" or c["kem"] != "ML-KEM-512"), "exact", "", P,
        "fit_matrix.json c_reader (C-priv or C-min ML-KEM-768/1024)")

    def crow(a, s, k):
        return [c for c in cr if c["arch"] == a and c["sig"] == s and c["kem"] == k][0]
    add("CprivFnFiveKemFiveTxMs", F(crow("C-priv", "FN-DSA-512", "ML-KEM-512")["reader_tx_ms"]) / 1000, "ms3", "ms", P,
        "fit_matrix.json c_reader")
    add("CprivFnFiveKemFiveTxFloorMs", F(crow("C-priv", "FN-DSA-512", "ML-KEM-512")["reader_tx_ms"]) / 1000, "lb1", "ms", P,
        "fit_matrix.json c_reader (lower bound)")
    add("CminFnFiveKemSevenTxMs", F(crow("C-min", "FN-DSA-512", "ML-KEM-768")["reader_tx_ms"]) / 1000, "ms3", "ms", P,
        "fit_matrix.json c_reader")
    for s, nm in (("FN-DSA-512", "FnFive"), ("FN-DSA-1024", "FnTen"), ("ML-DSA-44", "MlFour")):
        c = crow("C-min", s, "ML-KEM-512")
        add("Cmin%sKemFiveTxMs" % nm, F(c["reader_tx_ms"]) / 1000, "ms3", "ms", P, "fit_matrix.json c_reader")
        add("Cmin%sKemFiveGapsMs" % nm, F(c["fdt_pcd_ms"]) / 1000, "ms1", "ms", P, "fit_matrix.json c_reader")
    cp = one(arch="C-priv", sig="FN-DSA-512", kem="ML-KEM-512")
    add("CprivExtFourKiloReaderMs", F(cp["sensitivity"]["FSD/FSC 4096 + extended"]["reader_fixed_ms"]) / 1000, "lb1", "ms",
        P, "results.json transport sensitivity")
    add("CprivReaderMs", F(cp["reader_fixed"]), "ms1", "ms", P, "results.json transport reader_fixed")
    add("CprivReaderDFourMs", F(cp["sensitivity"]["D=4 (424 kbit/s, out of spec)"]["reader_fixed_ms"]) / 1000, "ms1", "ms",
        P, "results.json transport sensitivity")

    # ---- F6 (E3)
    ab = [t for t in rows() if t["arch"] in ("A", "B") and t["sig"] in ("ML-DSA-65", "ML-DSA-87")]
    add("FsixReaderLoMs", min(reader_fixed(t) for t in ab), "ms1", "ms", P, "results.json transport (A: -FDT, E3)", "E3")
    add("FsixReaderHiMs", max(reader_fixed(t) for t in ab), "ms1", "ms", P, "results.json transport (A: -FDT, E3)", "E3")
    add("FsixFramesLoMs", min(F(t["sensitivity"]["gaps unassigned (D-T1b)"]["reader_fixed_ms"]) for t in ab) / 1000,
        "ms1", "ms", P, "results.json transport sensitivity D-T1b")
    add("FsixFramesHiMs", max(F(t["sensitivity"]["gaps unassigned (D-T1b)"]["reader_fixed_ms"]) for t in ab) / 1000,
        "ms1", "ms", P, "results.json transport sensitivity D-T1b")
    add("GapMs", GAP, "ms3", "ms", P, "FDT_A,PCD,MIN 6780/fc (correction E3)", "E3")

    # ---- F7
    sigs7 = ("ML-DSA-44", "ML-DSA-65", "ML-DSA-87", "FN-DSA-1024")
    a7 = [one(arch="A", sig=s) for s in sigs7]
    ab7 = [t for t in rows() if t["arch"] in ("A", "B") and t["sig"] in sigs7]
    add("FsevenCardLoMs", min(F(t["card_fixed"]) for t in a7), "ms1", "ms", P, "results.json transport card_fixed")
    add("FsevenCardHiMs", max(F(t["card_fixed"]) for t in a7), "ms1", "ms", P, "results.json transport card_fixed")
    for s, nm in zip(sigs7, ("MlFour", "MlSix", "MlEight", "FnTen")):
        add("A%sCardMs" % nm, F(one(arch="A", sig=s)["card_fixed"]), "ms3", "ms", P, "results.json transport card_fixed")
    add("ABCardMaxDiffMs", max(abs(F(one(arch="A", sig=s)["card_fixed"]) - F(one(arch="B", sig=s)["card_fixed"]))
                                for s in sigs7), "ms1", "ms", P, "results.json transport (max |A-B| card)")
    add("FsevenFieldLoMs", min(field_fixed(t) for t in ab7), "ms1", "ms", P, "results.json transport (A: -FDT, E3)", "E3")
    add("FsevenFieldHiMs", max(field_fixed(t) for t in ab7), "ms1", "ms", P, "results.json transport (A: -FDT, E3)", "E3")
    add("AMlFourDepthOneCardMs", F(one(arch="A", sig="ML-DSA-44", depth=1)["card_fixed"]), "lb1", "ms", P,
        "results.json transport depth 1")
    add("AMlFourExtFourKiloCardMs", min(F(one(arch=a, sig="ML-DSA-44")["sensitivity"]["FSD/FSC 4096 + extended"]["card_fixed_ms"])
                                        for a in ("A", "B")) / 1000, "lb1", "ms", P, "results.json sensitivity")
    add("AMlFourDFourCardMs", F(one(arch="A", sig="ML-DSA-44")["sensitivity"]["D=4 (424 kbit/s, out of spec)"]["card_fixed_ms"]) / 1000,
        "ms1", "ms", P, "results.json sensitivity")
    add("AMlFourCardFloorMs", F(one(arch="A", sig="ML-DSA-44")["card_fixed"]), "ms1", "ms", P, "results.json transport")
    add("AFnTenCardOneMs", F(one(arch="A", sig="FN-DSA-1024")["card_fixed"]), "ms1", "ms", P, "results.json transport")
    ex, _, _ = R.build("A", "FN-DSA-1024", None, 2)
    add("AFnTenDTwoCardMs", R.fixed_times(ex, Link(divisor=2))[1], "ms1", "ms", "run.build + run.fixed_times (Link divisor 2)",
        "model (frontier)")

    # ---- F8 (results.json ram rows)
    def ram(scheme, op, impl):
        r = [x for x in RES["ram"] if x["scheme"] == scheme and x["op"] == op and x["impl"] == impl]
        need(len(r) == 1, (scheme, op, impl))
        return F(r[0]["required_bytes"])
    add("MlFourCleanRamBytes", ram("ML-DSA-44", "sign", "pqm4 clean"), "exact", "B", P, "results.json ram")
    add("MlFourPqmThreeCleanRamBytes", ram("ML-DSA-44", "sign", "pqm3 clean"), "exact", "B", P, "results.json ram")
    add("MlFourPqmThreeMThreeRamBytes", ram("ML-DSA-44", "sign", "pqm3 m3"), "exact", "B", P, "results.json ram")
    m0p = ram("ML-DSA-44", "sign", "M0+ PQClean")
    add("MlFourMZeroPRamBytes", rnd(m0p, 1), "pub", "B", P, "results.json ram (M0+ total, 1 dp)")
    add("MlFourSmallestRamKB", min(ram("ML-DSA-44", "sign", i) for i in ("pqm4 clean", "pqm3 clean", "pqm3 m3", "M0+ PQClean")),
        "kb1", "KB (1000 B)", P, "results.json ram (smallest executable on SC300/SC000)")
    add("MlFourRamRatio", min(ram("ML-DSA-44", "sign", i) for i in ("pqm4 clean", "pqm3 clean", "pqm3 m3", "M0+ PQClean"))
        / 16000, "x1", "", P, "smallest / 16 KB (1000-byte KB)")
    add("MlFourStackRamBytes", ram("ML-DSA-44", "sign", "pqm4 m4fstack"), "exact", "B", P, "results.json ram")
    gks = [x for x in RES["ram"] if x["impl"] == "GKS21 strategy 3"]
    add("GksStackLoBytes", min(int(x["work_ram"]) for x in gks), "exact", "B", P, "results.json ram (GKS21 work_ram)")
    add("GksStackHiBytes", max(int(x["work_ram"]) for x in gks), "exact", "B", P, "results.json ram (GKS21 work_ram)")
    add("GksRamLoBytes", min(F(x["required_bytes"]) for x in gks), "exact", "B", P, "results.json ram (GKS21)")
    add("GksRamHiBytes", max(F(x["required_bytes"]) for x in gks), "exact", "B", P, "results.json ram (GKS21)")
    gc = [i for i in RES["card_impls"] if i["id"] == "GKS21 strategy 3"]
    add("GksCyclesLoM", min(i["cycles"] for i in gc), "mcyc1", "M cycles", P, "results.json card_impls (GKS21 strategy 3)")
    add("GksCyclesHiM", max(i["cycles"] for i in gc), "mcyc1", "M cycles", P, "results.json card_impls (GKS21)")
    b = LIT_EXTRA["brs22"]
    add("BrsSignKiB", b["sign_kib"]["Dilithium-2"], "pub", "KiB", P, "data/literature_extra.json brs22 (Table 2)", "E4")
    brs_ram = int(Decimal(b["sign_kib"]["Dilithium-2"]) * 1024) + b["sig_bytes_round3"]["Dilithium-2"] + R.MSG + R.APDU_BUF
    add("BrsRamBytes", brs_ram, "exact", "B", P, "brs22 stack x 1024 + sig + MSG + APDU_BUF (D-M1)", "E4")
    add("BrsCyclesM", b["sign_kcc"]["Dilithium-2"] * 1000, "mcyc2", "M cycles", P, "brs22 Table 2 kcc", "E4")
    add("BrsCardMs", F(b["sign_kcc"]["Dilithium-2"] * 1000, 80_000_000), "ms1", "ms", P, "brs22 cycles / 80 MHz", "E4")

    # ---- F9 / E1 (kernel8_rmin.json; T13)
    ap = [a for a in RMIN["applied"] if a["cfg"] == ["C-min", "FN-DSA-512", "ML-KEM-512", 2, 512]][0]
    ex, _, rops = R.build("C-min", "FN-DSA-512", "ML-KEM-512", 2)
    L512 = Link(fsd=512, fsc=512)
    t = closed_form(ex, L512)
    fixed = t.reader_frames + t.pcd_gaps * L512.t_fdt_pcd
    add("FnineAuthMs", fixed, "ms3", "ms", "run.build + closed_form (FSD 512)", "results/kernel8_rmin.json applied")
    add("FnineLeftMs", R.READER_BUDGET - fixed, "ms3", "ms", P, "100 ms - FnineAuthMs")
    rmin = F(RMIN["R_min_frames_gaps"])
    add("RminMs", rmin, "ms3", "ms", P, "results/kernel8_rmin.json R_min_frames_gaps", "E1")
    add("RminFramesMs", F(RMIN["frames"]), "ms3", "ms", P, "results/kernel8_rmin.json frames", "E1")
    add("RminGapsMs", F(RMIN["gaps_s"]), "ms3", "ms", P, "results/kernel8_rmin.json gaps_s", "E1")
    add("RminGapCount", RMIN["gaps"], "exact", "", P, "results/kernel8_rmin.json gaps", "E1")
    m = R.READER_BUDGET - fixed - rmin
    add("FnineMarginMs", m, "ms3", "ms", P, "kernel8_rmin.json left_fg_ms (exact from T13)", "E1")
    add("FnineMarginTpMs", m - 2 * F(RMIN["t_p"]), "ms3", "ms", P, "kernel8_rmin.json left_tp_ms", "E1")
    from math import ceil
    hz = ceil(F(ap["reader_cycles"]) / m)
    add("FnineClockMHz", hz, "mhz1", "MHz", P, "kernel8_rmin.json mhz_fg (exact Hz from T13)", "E1")
    add("FnineClockGHz", hz, "ghz1", "GHz", P, "kernel8_rmin.json mhz_fg", "E1")
    add("FnineReaderCycles", ap["reader_cycles"], "exact", "cycles", P, "kernel8_rmin.json reader_cycles")
    add("ClassicalLeftMs", F(RMIN["classical_left_with_tp_ms"]) / 1000, "ms3", "ms", P, "kernel8_rmin.json classical_left_with_tp_ms", "E1")
    t1b = [a for a in REST["applied"] if a["arch"] == "C-min" and a["depth"] == 2 and a["sig"] == "FN-DSA-512"
           and a["kem"] == "ML-KEM-512"]
    for fs, nm in ((256, "Min"), (512, "FiveTwelve")):
        v = [a for a in t1b if a["fs"] == fs][0]["modes"]["T1b frames only"]["reader_mhz"]
        add("TonebClock%sMHz" % nm, F(v) * 10**6, "mhz1", "MHz", P, "kernel8_rest.json applied T1b (3-dp JSON)")

    # ---- F10 (fit_matrix decomposition; model for the exact cycle budgets)
    def dec_row(arch, depth, impl):
        return [d for d in FIT["fndsa512_decomposition"] if d["arch"] == arch and d["depth"] == depth and d["impl"] == impl][0]
    add("AFnFiveCardMs", F(one(arch="A", sig="FN-DSA-512")["card_fixed"]), "ms1", "ms", P, "results.json transport card_fixed")
    p26 = dec_row("A", 2, "Pornin 2026 RAM-efficient")
    add("PornTwentySixClockMHz", p26["required_hz"], "mhz1", "MHz", P, "fit_matrix.json decomposition")
    add("PornTwentySixClockOneMHz", p26["required_hz"], "mhz1", "MHz", P, "fit_matrix.json decomposition")
    add("PornTwentySixOverScThree", F(p26["required_hz"], 80_000_000), "x1", "", P, "required_hz / 80 MHz")
    ref = dec_row("A", 2, "pqm4 ref")
    add("RefClockMHz", ref["required_hz"], "mhz1", "MHz", P, "fit_matrix.json decomposition")
    add("RefCycles", ref["cycles"], "exact", "cycles", P, "fit_matrix.json decomposition")
    add("RefRamBytes", ram("FN-DSA-512", "sign", "pqm4 ref"), "exact", "B", P, "results.json ram")
    add("FtenComputeMs", F(ref["computation_ms"]) / 1000, "ms1", "ms", P, "fit_matrix.json decomposition (6-dp JSON)")

    def maxcyc(arch, depth, link, f=80_000_000):
        exs, _, _ = R.build(arch, "FN-DSA-512", None, depth)
        tot, _, _ = R.fixed_times(exs, link)

        def ok(c):
            return evaluate_closed(tot, link, {("sign",): F(c, f)}, True)["card"] <= R.CARD_BUDGET
        lo, hi = 0, 10 ** 9
        while lo < hi:
            mid = (lo + hi + 1) // 2
            lo, hi = (mid, hi) if ok(mid) else (lo, mid - 1)
        return lo
    mc = maxcyc("A", 2, Link())
    add("FtenMaxCycles", mc, "exact", "cycles", "make_numbers.maxcyc (run.build, evaluate_closed, 80 MHz)", "model")
    add("FtenMaxCyclesM", mc, "mcyc2", "M cycles", "make_numbers.maxcyc", "model")
    add("FtenMaxCyclesDTwoM", maxcyc("A", 2, Link(divisor=2)), "mcyc1", "M cycles", "make_numbers.maxcyc (divisor 2)", "model")
    add("FtenMaxCyclesDepthOneM", maxcyc("A", 1, Link()), "mcyc1", "M cycles", "make_numbers.maxcyc (depth 1)", "model")
    add("FtenMaxCyclesFsFiveM", maxcyc("A", 2, Link(fsd=512, fsc=512)), "mcyc2", "M cycles", "make_numbers.maxcyc (FSD 512)",
        "model")
    add("PornTwentySixCycles", p26["cycles"], "exact", "cycles", P, "fit_matrix.json decomposition")
    add("PornTwentySixCyclesM", p26["cycles"], "mcyc2", "M cycles", P, "fit_matrix.json decomposition")
    add("PornTwentySixRamBytes", ram("FN-DSA-512", "sign", "Pornin 2026 RAM-efficient"), "exact", "B", P, "results.json ram")

    # ---- F11
    def clk(impl):
        r = [x for x in RES["computation"] if x["arch"] == "C-min" and x["depth"] == 2 and x["sig"] == "FN-DSA-512"
             and x["kem"] == "ML-KEM-512" and x["impl"] == impl][0]
        return F(r["required_card_clock_mhz"]) * 10**6
    add("DecapsMThreeClockMHz", clk("pqm3 m3"), "mhz1", "MHz", P, "results.json computation (3-dp JSON)")
    add("DecapsMThreeClockExactMHz", clk("pqm3 m3"), "mhz3", "MHz", P, "results.json computation", group_digits=False)
    add("DecapsMZeroClockMHz", clk("M0+ PQClean"), "mhz1", "MHz", P, "results.json computation (3-dp JSON)")
    add("DecapsMZeroClockExactMHz", clk("M0+ PQClean"), "mhz3", "MHz", P, "results.json computation", group_digits=False)
    add("DecapsMThreeMargin", F(80 * 10**6) / clk("pqm3 m3"), "x1", "", P, "80 MHz / clock")
    add("DecapsMZeroMargin", F(60 * 10**6) / clk("M0+ PQClean"), "x1", "", P, "60 MHz / clock")
    add("DecapsMThreeRamBytes", ram("ML-KEM-512", "decaps", "pqm3 m3"), "exact", "B", P, "results.json ram")
    add("EncapsMThreeRamBytes", ram("ML-KEM-512", "encaps", "pqm3 m3"), "exact", "B", P, "results.json ram", "E5")
    add("DecapsSevenMThreeRamBytes", ram("ML-KEM-768", "decaps", "pqm3 m3"), "exact", "B", P, "results.json ram", "E5")
    add("AlnRamKB", LIT_EXTRA["aln25"]["ram_available_kb"], "pub", "kB", P, "data/literature_extra.json aln25", "E5")
    add("AlnRamBytes", RAM45["limits_bytes"]["4500"], "exact", "B", P, "results/ram_4500.json limits", "E5")
    add("AlnFitsPaymentCore", len(RAM45["fit_4500_payment_core"]), "exact", "", P, "results/ram_4500.json", "E5")

    # ---- F12 (E3 on A)
    add("RsaCardMs", F(one(arch="A-classical")["card_fixed"]), "ms3", "ms", P, "results.json transport")
    add("RsaReaderMs", reader_fixed(one(arch="A-classical")), "ms3", "ms", P, "results.json transport (-FDT, E3)", "E3")
    add("EccCardMs", F(one(arch="C-classical")["card_fixed"]), "ms3", "ms", P, "results.json transport")
    add("EccReaderMs", F(one(arch="C-classical")["reader_fixed"]), "ms3", "ms", P, "results.json transport")

    # ---- F14 (IDEMIA)
    for q, nm in zip(RES["idemia"], ("FalconFive", "FalconTen", "DilTwo", "DilThree")):
        add("Idemia%sBytes" % nm, q["idemia_theoretical"], "exact", "B", P, "results.json idemia")
    add("IdemiaHeaderBytes", RES["idemia"][0]["difference"], "exact", "B", P, "results.json idemia difference")

    # ---- F15 / E2 (kernel8_rmin applied, depth 1)
    d1 = [a for a in RMIN["applied"] if a["cfg"][3] == 1]
    best = max(d1, key=lambda a: F(a["left_tp_ms"]))
    add("FfifteenBestTpMs", F(best["left_tp_ms"]) / 1000, "ms3", "ms", P, "kernel8_rmin.json applied (4-dp JSON)", "E2")
    for sig, fs, nm in (("FN-DSA-512", 512, "FnFiveFs"), ("FN-DSA-1024", 512, "FnTenFs"),
                        ("FN-DSA-512", 256, "FnFiveFsMin"), ("ML-DSA-44", 512, "MlFourFs")):
        a = [x for x in d1 if x["cfg"][1] == sig and x["cfg"][4] == fs][0]
        add("Ffifteen%sMHz" % nm, F(a["mhz_fg"]) * 10**6, "mhz1", "MHz", P, "kernel8_rmin.json applied mhz_fg", "E2")

    
    # ---- PQ-EAC, masking (cannot-say list)
    add("PqeacRamKB", LIT_EXTRA["pqeac"]["ram_kbytes"], "exact", "KB", P, "data/literature_extra.json pqeac")
    s8 = J("results/protected_mlkem.json")
    b25 = LIT_EXTRA["bdg25"]
    add("BdgHybridMs", b25["mode_b_128_hybrid_processing_ms"], "exact", "ms", P, "data/literature_extra.json bdg25 (SECRYPT Tab. 3/4)", "E6")
    add("BdgClassicMs", b25["mode_b_128_classic_processing_ms"], "exact", "ms", P, "data/literature_extra.json bdg25 (ePrint Tab. 4)", "E6")
    add("BdgIncrementMs", s8["bdg25_increment_ms"], "exact", "ms", P, "results/protected_mlkem.json", "E6")
    add("BdgClockMHz", b25["clock_hz"], "mhz0x", "MHz", P, "data/literature_extra.json bdg25", "E6")
    add("BdgIncrementM", F(s8["bdg25_increment_cycles"]), "mcyc1", "M cycles", P, "results/protected_mlkem.json", "E6")
    add("HardDecapsLoM", F(s8["decaps_lo_cycles"]), "mcyc1", "M cycles", P, "results/protected_mlkem.json (KeyGen = Decaps)", "E6")
    add("HardDecapsHiM", F(s8["decaps_hi_cycles"]), "mcyc1", "M cycles", P, "results/protected_mlkem.json (KeyGen ~ 0)", "E6")
    add("HardDecapsLoCycles", round(F(s8["decaps_lo_cycles"])), "exact", "cycles", P, "results/protected_mlkem.json (rounded to integer)", "E6")
    add("HardDecapsHiCycles", F(s8["decaps_hi_cycles"]), "exact", "cycles", P, "results/protected_mlkem.json", "E6")
    add("HardRatioLo", F(s8["ratio_lo"]), "x1", "", P, "results/protected_mlkem.json", "E6")
    add("HardRatioHi", F(s8["ratio_hi"]), "x1", "", P, "results/protected_mlkem.json", "E6")
    add("UnprotDecapsCycles", s8["unprotected_pqm3_m3_decaps_cycles"], "exact", "cycles", P, "results.json card_impls pqm3 m3", "E6")
    for b in s8["budgets"]:
        nmb = {80_000_000: "ScThree", 60_000_000: "StNSix", 55_000_000: "StPFour"}[b["clock_hz"]]
        add("DecapsBudget%sCycles" % nmb, b["budget_cycles"], "exact", "cycles", P, "results/protected_mlkem.json budgets", "E6")
    tables()
    figs()
    # text macros
    add("TestsModelCount", len(RES["tests"]), "exact", "", P, "results.json tests (run.py T01-T12)")
    import test_rmin_by_hand
    add("TestsTThirteenCount", len(test_rmin_by_hand.t13()), "exact", "", P, "tests/test_rmin_by_hand.py t13()")
    dz = LIT_EXTRA["dz26"]
    add("DzKemRatio", dz["mlkem512_decaps_over_ecdsa256"], "pub", "", P, "data/literature_extra.json dz26", "E7")
    add("DzDsaLo", dz["mldsa44_sign_over_ecdsa256"][0], "pub", "", P, "data/literature_extra.json dz26", "E7")
    add("DzDsaHi", dz["mldsa44_sign_over_ecdsa256"][1], "pub", "", P, "data/literature_extra.json dz26", "E7")
    add("DzRateKbps", dz["comm_rate_kbps"], "exact", "kbit/s", P, "data/literature_extra.json dz26", "E7")
    add("DzClockMHz", dz["clock_hz"], "mhz0x", "MHz", P, "data/literature_extra.json dz26", "E7")
    add("PqeacRuntimeS", LIT_EXTRA["pqeac"]["total_runtime_s"], "pub", "s", P, "data/literature_extra.json pqeac")
    mk = cat.LIT["masking"]
    add("MaskFactor", F(mk["mldsa_sign_2share_randomized"]), "x1", "", P,
        "data/literature.json masking (AZ22 §6.3; TCHES 2023(4) p. 72)")
    add("MaskFactorDet", F(mk["mldsa_sign_2share_deterministic"]), "x2", "", P,
        "data/literature.json masking (AZ22 §6.3; TCHES 2023(4) p. 72)")


DIGIT = ["Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"]


def nm(s):
    """Macro-safe CamelCase name: letters kept, each digit spelled out."""
    out = []
    for w in re.split(r"[^A-Za-z0-9]+", s or ""):
        if not w:
            continue
        w = "".join(DIGIT[int(c)] if c.isdigit() else c for c in w)
        out.append(w[0].upper() + w[1:].lower() if w.isupper() or w.islower() else w[0].upper() + w[1:])
    return "".join(out)


TABLES = {}


def tables():
    """Systematic macros for the drafting tables (TABLES holds the row keys)."""
    P = "paper/make_numbers.py:tables"
    # transport, depth 2, all architectures (E3 applied to A)
    TABLES["transport"] = []
    for t in RES["transport"]:
        if t["depth"] != 2:
            continue
        key = nm("%s %s %s" % (t["arch"], t["sig"] or "", t["kem"] or ""))
        e3 = "E3" if t["arch"] in ("A", "A-classical") else ""
        add("Tr%sCardMs" % key, F(t["card_fixed"]), "ms3", "ms", P, "results.json transport card_fixed")
        add("Tr%sReaderMs" % key, reader_fixed(t), "ms3", "ms", P, "results.json transport reader_fixed" + (" (-FDT, E3)" if e3 else ""), e3)
        add("Tr%sFieldMs" % key, field_fixed(t), "ms3", "ms", P, "results.json transport card+reader" + (" (-FDT, E3)" if e3 else ""), e3)
        TABLES["transport"].append((t["arch"], t["sig"], t["kem"], key))
    # R_min terms (kernel8_rmin)
    sys.path.insert(0, os.path.join(ROOT, "analyses")); sys.path.insert(0, os.path.join(ROOT, "tests"))
    import kernel8_rmin as S5
    TABLES["rmin"] = []
    for name, byt, etu, g, clause, basis in S5.TERMS:
        if name.startswith("t_P"):
            v = F(RMIN["t_p"])
        elif name.startswith("WUPB"):
            v = S5.wupb_time()
        else:
            v = etu * F(128, FC)
        key = nm(name)
        add("Rmin%sMs" % key, v, "ms3", "ms", P, "analyses/kernel8_rmin.py TERMS (T13)", "E1")
        add("Rmin%sGaps" % key, g, "exact", "", P, "analyses/kernel8_rmin.py TERMS (T13)", "E1")
        TABLES["rmin"].append((name, byt, etu, g, clause, basis, key))
    # remainder applied (F9, F15; E1/E2)
    TABLES["applied"] = []
    for a in RMIN["applied"]:
        arch, sig, kem, depth, fs = a["cfg"]
        key = nm("%s %s %s d%s fs%s" % (arch, sig, kem, depth, fs))
        err = "E1" if depth == 2 else "E2"
        add("Ap%sAuthMs" % key, F(a["reader_fixed_ms"]) / 1000, "ms3", "ms", P, "kernel8_rmin.json applied", err)
        add("Ap%sLeftMs" % key, F(a["left_fg_ms"]) / 1000, "ms3", "ms", P, "kernel8_rmin.json applied (4-dp JSON)", err)
        add("Ap%sLeftTpMs" % key, F(a["left_tp_ms"]) / 1000, "ms3", "ms", P, "kernel8_rmin.json applied (4-dp JSON)", err)
        if a["mhz_fg"] != "none":
            add("Ap%sMHz" % key, F(a["mhz_fg"]) * 10**6, "mhz1", "MHz", P, "kernel8_rmin.json applied", err)
        TABLES["applied"].append((arch, sig, kem, depth, fs, key, a["mhz_fg"] != "none"))
    # RAM rows (D-M1) with the 4.5 kB sensitivity (E5)
    TABLES["ram"] = []
    fit45 = {(r[0], r[1], r[2]) for r in RAM45["fit_4500_payment_core"]}
    for x in RES["ram"]:
        if x.get("required_bytes") is None:
            continue
        key = nm("%s %s %s" % (x["scheme"], x["op"], x["impl"]))
        req = F(x["required_bytes"])
        add("Ram%sBytes" % key, req if req.denominator == 1 else rnd(req, 1), "exact" if req.denominator == 1 else "pub", "B",
            P, "results.json ram required_bytes (D-M1)")
        TABLES["ram"].append((x["scheme"], x["op"], x["impl"], x["runs_on"], key, x.get("fits_kb1024", {}),
                              (x["scheme"], x["op"], x["impl"]) in fit45 or req <= 4500))
    # C reader transmission and gaps, depth 2, FSD 256 (F4, F5)
    TABLES["creader"] = []
    for c in FIT["c_reader"]:
        if c["depth"] != 2:
            continue
        key = nm("%s %s %s" % (c["arch"], c["sig"], c["kem"]))
        add("Cr%sTxMs" % key, F(c["reader_tx_ms"]) / 1000, "ms3", "ms", P, "fit_matrix.json c_reader reader_tx_ms")
        add("Cr%sGapsMs" % key, F(c["fdt_pcd_ms"]) / 1000, "ms3", "ms", P, "fit_matrix.json c_reader fdt_pcd_ms")
        TABLES["creader"].append((c["arch"], c["sig"], c["kem"], key, c["exceeds_tx_only"], c["exceeds_with_gaps"]))
    # chips
    TABLES["chips"] = []
    for c, d in cat.chips().items():
        key = nm(c)
        if d["clock_mhz"] is not None:
            add("Chip%sMHz" % key, d["clock_mhz"] * 10**6, "mhz0x", "MHz", P, "data/literature.json chips")
        add("Chip%sRamKB" % key, d["ram_kb"], "exact", "KB", P, "data/literature.json chips")
        TABLES["chips"].append((c, d, key))


def figs():
    """Macros for every number printed on a figure Values come from
    results.json, the analysis JSONs and results/figure_data.json."""
    P = "paper/make_numbers.py:figs"
    FIGDATA = J("results/figure_data.json")
    tp2 = 2 * F(RMIN["t_p"])
    rmin = F(RMIN["R_min_frames_gaps"])
    # F-card: architecture A (+ classical RSA), depth 2, card fixed time
    for sig in (None, "ML-DSA-44", "ML-DSA-65", "ML-DSA-87", "FN-DSA-512", "FN-DSA-1024"):
        t = one(arch="A-classical") if sig is None else one(arch="A", sig=sig)
        add("FigCard%sMs" % nm(sig or "RSA"), F(t["card_fixed"]), "ms1", "ms", P, "results.json transport card_fixed")
    # F-reader: C configurations at FSD 256 (+ R_min + 2 t_P), F9 bar at FSD 512, classical ECC
    for c in FIT["c_reader"]:
        if c["depth"] != 2:
            continue
        tot = F(c["reader_tx_ms"]) / 1000 + F(c["fdt_pcd_ms"]) / 1000 + rmin + tp2
        add("FigReader%sMs" % nm("%s %s %s" % (c["arch"], c["sig"], c["kem"])), tot, "ms1", "ms", P,
            "fit_matrix.json c_reader + kernel8_rmin.json R_min + 2 t_P", "E1")
    f9 = FIGDATA["f9_fs512"]
    add("FigReaderFnineMs", F(f9["reader_frames"]) + F(f9["pcd_gaps_s"]) + rmin + tp2, "ms1", "ms", P,
        "figure_data.json f9_fs512 + R_min + 2 t_P", "E1")
    ce = one(arch="C-classical")
    add("FigReaderEccMs", F(ce["reader_fixed"]) + rmin + tp2, "ms1", "ms", P,
        "results.json transport C-classical + R_min + 2 t_P", "E1")
    # F-clock
    m4f = [d for d in FIT["fndsa512_decomposition"] if d["arch"] == "A" and d["depth"] == 2 and d["impl"] == "pqm4 m4f"][0]
    add("FnFiveMFourfClockMHz", m4f["required_hz"], "mhz1", "MHz", P, "fit_matrix.json decomposition")
    hc = FIGDATA["hardened_decaps_clock_hz"]
    add("HardClockLoMHz", hc["lo_hz"], "mhz1", "MHz", P, "figure_data.json (E6 lower bound)", "E6")
    add("HardClockHiMHz", hc["hi_hz"], "mhz1", "MHz", P, "figure_data.json (E6 upper bound)", "E6")


# ---------------------------------------------------------------- output

def render():
    build()
    tex = ["% Generated by paper/make_numbers.py -- do not edit. Values: paper/numbers_manifest.csv",
           "% Rounding rules: see the module docstring of paper/make_numbers.py."]
    for m in MACROS:
        tex.append("\\newcommand{\\%s}{%s}%% %s %s" % (m["macro"], m["printed"].replace(" ", "\\,").replace("-", "\\ensuremath{-}", 1)
                                                         if m["printed"].startswith("-") else m["printed"].replace(" ", "\\,"),
                                                         m["units"], ("[" + m["erratum"] + "]") if m["erratum"] else ""))
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["macro", "value as printed", "exact value", "units", "producing file/function",
                "source artifact", "erratum", "rounding rule"])
    for m in MACROS:
        w.writerow([m["macro"], m["printed"], m["exact"], m["units"], m["producer"], m["source"], m["erratum"], m["rule"]])
    return "\n".join(tex) + "\n", buf.getvalue()


def main():
    tex, man = render()
    tp = os.path.join(ROOT, "paper", "numbers.tex")
    mp = os.path.join(ROOT, "paper", "numbers_manifest.csv")
    if "--check" in sys.argv:
        for p, new in ((tp, tex), (mp, man)):
            old = open(p, encoding="utf-8").read() if os.path.exists(p) else None
            if old != new:
                raise SystemExit("numbers pipeline: %s differs from a fresh regeneration" % os.path.relpath(p, ROOT))
        print("numbers pipeline: %d macros, regenerated identically" % len(MACROS))
        return
    os.makedirs(os.path.dirname(tp), exist_ok=True)
    for p, new in ((tp, tex), (mp, man)):
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(new)
    print("wrote %d macros" % len(MACROS))


if __name__ == "__main__":
    main()
