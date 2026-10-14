"""Figures of the paper: reader time (Fig. 3), card RAM (Fig. 4) and card clock (Fig. 5).

Every plotted value is read from results/; every number printed on a figure
is a macro of paper/numbers.tex. Each figure's values are written to
paper/figures/<name>_data.csv, and the PDF stores the SHA-256 of that CSV in
its metadata, so the check below can tie each PDF to its data without
matplotlib.

Usage: python paper/make_figures.py            write the CSVs (and the PDFs if matplotlib is installed)
       python paper/make_figures.py --check    the CSVs must regenerate exactly and match their PDFs
"""
import csv
import hashlib
import io
import json
import os
import sys
from fractions import Fraction as F

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "paper"))
import make_numbers as E                                  # noqa: E402

FIGS = os.path.join(ROOT, "paper", "figures")
PALETTE = {"blue": "#0072B2", "orange": "#E69F00", "green": "#009E73", "vermillion": "#D55E00",
           "purple": "#CC79A7", "sky": "#56B4E9", "grey": "#999999", "black": "#000000"}   # Okabe-Ito
CM = 1 / 2.54
FULL, HALF = 12.2 * CM, 5.9 * CM


def J(p):
    return json.load(open(os.path.join(ROOT, p), encoding="utf-8"))


def fr(x):
    x = F(x)
    return "%d/%d" % (x.numerator, x.denominator) if x.denominator != 1 else str(x.numerator)


def ms(x):
    return "%.6f" % (float(F(x)) * 1000)


# ------------------------------------------------------------------- data

def data():
    E.build()
    mac = {m["macro"]: m["printed"] for m in E.MACROS}
    RES, FIT, RMIN, FIGDATA = J("results/results.json"), J("results/fit_matrix.json"), J("results/kernel8_rmin.json"), \
        J("results/figure_data.json")

    def lab(name):
        return name, mac[name]

    def row(kind, **kw):
        kw["kind"] = kind
        return kw

    def tr(**k):
        return [t for t in RES["transport"] if t["depth"] == 2 and all(t[a] == b for a, b in k.items())][0]

    figs = {}
    thr = {"card": lab("CardTariffMs"), "field": lab("FieldTargetMs"), "reader": lab("ReaderTariffMs")}

    # F-reader: architecture C with ML-KEM-512, depth 2, the configurations the paper shows.
    # Bar = authentication exchanges (reader frames + FDT gaps) + rest of transaction (R_min + two t_P waits).
    rmin, tp2 = F(RMIN["frames"]) + F(RMIN["gaps_s"]), 2 * F(RMIN["t_p"])
    rows = []

    def rbar(name, tx, gaps, macro):
        m, v = lab(macro)
        rows.append(row("bar", name=name, auth=fr(tx + gaps), auth_ms=ms(tx + gaps), rest=fr(rmin + tp2), rest_ms=ms(rmin + tp2),
                        reader_tx=fr(tx), pcd_gaps=fr(gaps), rmin=fr(rmin), tp=fr(tp2), label_macro=m, label=v))
    ce = tr(arch="C-classical")
    rbar("classical ECC (today)", F(ce["reader_tx_ms"]) / 1000, F(ce["reader_fixed"]) - F(ce["reader_tx_ms"]) / 1000,
         "FigReaderEccMs")
    f9 = FIGDATA["f9_fs512"]
    rbar("C-min, FN-DSA-512 (512-byte frames)", F(f9["reader_frames"]), F(f9["pcd_gaps_s"]), "FigReaderFnineMs")
    for arch, sig in (("C-min", "FN-DSA-512"), ("C-min", "ML-DSA-44"), ("C-priv", "FN-DSA-512"), ("C-priv", "ML-DSA-44")):
        c = [c for c in FIT["c_reader"] if c["depth"] == 2 and c["arch"] == arch and c["sig"] == sig and c["kem"] == "ML-KEM-512"][0]
        rbar("%s, %s" % (arch, sig), F(c["reader_tx_ms"]) / 1000, F(c["fdt_pcd_ms"]) / 1000,
             "FigReader%sMs" % E.nm("%s %s ML-KEM-512" % (arch, sig)))
    rows.append(row("threshold", name="reader", value_ms=thr["reader"][1], label_macro=thr["reader"][0], label=thr["reader"][1]))
    figs["reader_time"] = rows

    # F-ram: the rows the paper shows, top to bottom
    rows = []
    ram = {(x["scheme"], x["op"], x["impl"]): x for x in RES["ram"] if x.get("required_bytes") is not None}
    for name, key in (("ML-KEM-512 decaps, pqm3 (M3)", ("ML-KEM-512", "decaps", "pqm3 m3")),
                      ("ML-KEM-512 decaps, PQClean (M0+)", ("ML-KEM-512", "decaps", "M0+ PQClean")),
                      ("ML-DSA-44 sign, pqm4 m4fstack", ("ML-DSA-44", "sign", "pqm4 m4fstack")),
                      ("FN-DSA-512 sign, Pornin 2026", ("FN-DSA-512", "sign", "Pornin 2026 RAM-efficient")),
                      ("FN-DSA-512 sign, pqm4 ref", ("FN-DSA-512", "sign", "pqm4 ref")),
                      ("ML-DSA-44 sign, pqm3 (M3)", ("ML-DSA-44", "sign", "pqm3 m3")),
                      ("ML-DSA-44 sign, PQClean (M0+)", ("ML-DSA-44", "sign", "M0+ PQClean"))):
        x = ram[key]
        payment = any(c in x["runs_on"] for c in ("M3", "M0"))
        rows.append(row("point", name=name, impl=x["impl"], bytes=fr(F(x["required_bytes"])), payment_core=int(payment),
                        label_macro="", label=""))
    for m in ("StPFourRamKB", "SlcThreeSevenRamKB"):
        rows.append(row("reference", name=m, value=mac[m], label_macro=m, label=mac[m]))
    figs["card_ram"] = rows

    # F-clock: card clock for the implied card tariff, rows as in the paper
    rows = []
    for impl, name, m in (("pqm4 ref", "pqm4 ref", "RefClockMHz"), ("pqm4 m4f", "pqm4 m4f", "FnFiveMFourfClockMHz"),
                          ("Pornin 2026 RAM-efficient", "Pornin 2026", "PornTwentySixClockMHz")):
        d = [d for d in FIT["fndsa512_decomposition"] if d["arch"] == "A" and d["depth"] == 2 and d["impl"] == impl][0]
        rows.append(row("point", name="FN-DSA-512 sign, %s" % name, lo_hz=str(d["required_hz"]), hi_hz=str(d["required_hz"]),
                        m4_only=int(not any(c in d["runs_on"] for c in ("M3", "M0"))), inferred=0, label_macro=m, label=mac[m]))
    for impl, name, m in (("pqm3 m3", "pqm3 (M3)", "DecapsMThreeClockMHz"), ("M0+ PQClean", "PQClean (M0+)", "DecapsMZeroClockMHz")):
        c = [x for x in RES["computation"] if x["arch"] == "C-min" and x["depth"] == 2 and x["sig"] == "FN-DSA-512"
             and x["kem"] == "ML-KEM-512" and x["impl"] == impl][0]
        hz = F(c["required_card_clock_mhz"]) * 10 ** 6
        rows.append(row("point", name="ML-KEM-512 decaps, %s" % name, lo_hz=fr(hz), hi_hz=fr(hz), m4_only=0,
                        inferred=0, label_macro=m, label=mac[m]))
    hc = FIGDATA["hardened_decaps_clock_hz"]
    rows.append(row("range", name="ML-KEM-512 decaps, protected", lo_hz=str(hc["lo_hz"]), hi_hz=str(hc["hi_hz"]),
                    m4_only=0, inferred=1, label_macro="HardClockLoMHz;HardClockHiMHz",
                    label="%s;%s" % (mac["HardClockLoMHz"], mac["HardClockHiMHz"])))
    for m in ("StPFourClockMHz", "StNSixClockMHz", "ScThreeClockMHz"):
        rows.append(row("reference", name=m, lo_hz="", hi_hz="", m4_only="", inferred="", value=mac[m], label_macro=m,
                        label=mac[m]))
    figs["card_clock"] = rows
    return figs, mac


def to_csv(rows):
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=keys, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, "") for k in keys})
    return buf.getvalue()


# ------------------------------------------------------------------- plot

def plot(figs, mac, hashes, preview_dir=None):
    import warnings
    import matplotlib
    matplotlib.use("pdf")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    from matplotlib.ticker import FixedLocator, NullLocator, FuncFormatter
    plt.rcParams.update({"font.size": 8, "font.family": "serif", "pdf.fonttype": 42, "axes.linewidth": 0.6,
                         "xtick.major.width": 0.6, "ytick.major.width": 0.6, "xtick.labelsize": 7,
                         "ytick.labelsize": 7, "axes.spines.top": False, "axes.spines.right": False,
                         "legend.frameon": False, "legend.fontsize": 7, "legend.handlelength": 1.2,
                         "legend.columnspacing": 1.0})
    P = PALETTE

    def save(fig, name):
        fig.savefig(os.path.join(FIGS, name + ".pdf"), metadata={"CreationDate": None, "ModDate": None,
                    "Keywords": "csv-sha256=%s" % hashes[name], "Creator": "paper/make_figures.py"})
        if preview_dir:
            fig.savefig(os.path.join(preview_dir, name + ".png"), dpi=170)
        plt.close(fig)

    def canvas(h_cm):
        fig = plt.figure(figsize=(FULL, h_cm * CM), layout="constrained")
        fig.get_layout_engine().set(w_pad=0.02, h_pad=0.02)
        return fig, fig.add_subplot()

    def threshold(ax, value, text, y):
        ax.axvline(value, color=P["black"], lw=0.8, ls=(0, (4, 2)))
        ax.text(value, y, " " + text, ha="left", va="center", fontsize=7)

    # ---------------- reader time, card RAM, card clock
    style = {"font.family": "serif", "font.serif": ["cmr10"], "xtick.labelsize": 8, "ytick.labelsize": 8,
             "xtick.major.width": 0.8, "ytick.major.width": 0.8, "legend.fontsize": 7.5, "legend.handlelength": 2.0,
             "legend.columnspacing": 2.0}

    def sub_canvas(h_cm):
        fig = plt.figure(figsize=(FULL, h_cm * CM), layout="constrained")     # default 3 pt pads
        return fig, fig.add_subplot()

    def core_legend(fig):
        fig.legend(handles=[Patch(facecolor=P["blue"], edgecolor=P["blue"], lw=0.8, label="runs on the payment cores"),
                            Patch(facecolor="white", edgecolor=P["blue"], lw=0.8, label="needs Cortex-M4")],
                   loc="outside upper center", ncol=2)

    def band(ax, lo, hi, alpha, text, y):
        ax.axvspan(lo, hi, color=P["sky"], alpha=alpha, lw=0)
        ax.text((lo * hi) ** 0.5, y, text, ha="center", va="center", fontsize=7.5)

    def fixed_log(ax, ticks, fmt):
        ax.xaxis.set_major_locator(FixedLocator(ticks))
        ax.xaxis.set_minor_locator(NullLocator())
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: fmt(v)))

    with plt.rc_context(style), warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="cmr10 font should ideally")

        # ---------------- F-reader
        rows = [r for r in figs["reader_time"] if r["kind"] == "bar"]
        th = [r for r in figs["reader_time"] if r["kind"] == "threshold"][0]
        fig, ax = sub_canvas(4.4)
        y = list(range(len(rows)))[::-1]
        a = [float(F(r["auth"])) * 1000 for r in rows]
        b = [float(F(r["rest"])) * 1000 for r in rows]
        ax.barh(y, a, color=P["blue"], height=0.6, label="authentication exchanges")
        ax.barh(y, b, left=a, color=P["orange"], height=0.6, label="rest of transaction + polling waits")
        for yi, r, i, j in zip(y, rows, a, b):
            ax.text(i + j + 3, yi, r["label"] + " ms", va="center", fontsize=7.5)
        limit = float(th["value_ms"])
        ax.axvline(limit, color=P["black"], lw=0.9, ls="--")
        ax.text(limit + 2, len(rows) - 0.25, "reader limit %s ms" % th["label"], va="center", fontsize=7.5)
        ax.set_yticks(y)
        ax.set_yticklabels([r["name"] for r in rows])
        ax.set_xlim(0, 290)
        ax.set_ylim(-0.5, len(rows) + 0.2)
        ax.set_xlabel("reader time (ms), before any reader computation")
        fig.legend(loc="outside upper center", ncol=2)
        save(fig, "reader_time")

        # ---------------- F-ram
        rows = [r for r in figs["card_ram"] if r["kind"] == "point"]
        ref = {r["name"]: r for r in figs["card_ram"] if r["kind"] == "reference"}
        fig, ax = sub_canvas(4.6)
        ax.set_xscale("log")
        y = list(range(len(rows)))[::-1]
        for yi, r in zip(y, rows):
            ax.barh(yi, float(F(r["bytes"])), height=0.6, facecolor=P["blue"] if r["payment_core"] == 1 else "white",
                    edgecolor=P["blue"], lw=0.8)
        lo, hi = float(ref["StPFourRamKB"]["value"]) * 1024, float(ref["SlcThreeSevenRamKB"]["value"]) * 1024
        band(ax, lo, hi, 0.25, "chip RAM\n%s-%s KB" % (ref["StPFourRamKB"]["label"], ref["SlcThreeSevenRamKB"]["label"]),
             len(rows) + 0.45)
        ax.set_yticks(y)
        ax.set_yticklabels([r["name"] for r in rows])
        ax.set_ylim(-0.5, len(rows) + 0.5)
        ax.set_xlim(2000, 70000)
        fixed_log(ax, [2000, 5000, 10000, 20000, 50000], lambda v: "%d KB" % (v / 1000))
        ax.set_xlabel("card RAM needed (log scale)")
        core_legend(fig)
        save(fig, "card_ram")

        # ---------------- F-clock
        rows = [r for r in figs["card_clock"] if r["kind"] in ("point", "range")]
        ref = [r for r in figs["card_clock"] if r["kind"] == "reference"]
        fig, ax = sub_canvas(4.2)
        ax.set_xscale("log")
        y = list(range(len(rows)))[::-1]
        lo_r = min(ref, key=lambda r: float(r["value"]))
        hi_r = max(ref, key=lambda r: float(r["value"]))
        band(ax, float(lo_r["value"]), float(hi_r["value"]), 0.35, "chip clocks\n%s-%s MHz" % (lo_r["label"], hi_r["label"]),
             len(rows) + 0.45)
        for yi, r in zip(y, rows):
            lo, hi = float(F(r["lo_hz"])) / 1e6, float(F(r["hi_hz"])) / 1e6
            if r["kind"] == "range":
                ax.barh(yi, hi - lo, left=lo, height=0.6, color=P["vermillion"], lw=0)
                a_, b_ = r["label"].split(";")
                text = "%s-%s MHz (inferred)" % (a_, b_)
            else:
                ax.barh(yi, hi, height=0.6, facecolor="white" if r["m4_only"] == 1 else P["blue"], edgecolor=P["blue"],
                        lw=0.8)
                text = r["label"] + " MHz"
            ax.text(hi * 1.12, yi, text, va="center", fontsize=7.5)
        ax.set_yticks(y)
        ax.set_yticklabels([r["name"] for r in rows])
        ax.set_ylim(-0.5, len(rows) + 0.5)
        ax.set_xlim(1, 6000)
        fixed_log(ax, [1, 10, 100, 1000], lambda v: "%d" % v)
        ax.set_xlabel("card clock needed (MHz, log scale)")
        core_legend(fig)
        save(fig, "card_clock")


# ------------------------------------------------------------------- main

def check_labels(figs, mac):
    n = 0
    for name, rows in figs.items():
        for r in rows:
            if not r.get("label_macro"):
                continue
            for m, v in zip(r["label_macro"].split(";"), str(r["label"]).split(";")):
                if mac.get(m) != v:
                    raise SystemExit("figure %s: label %r is not macro \\%s (%r)" % (name, v, m, mac.get(m)))
                n += 1
    return n


def main():
    figs, mac = data()
    csvs = {n: to_csv(r) for n, r in figs.items()}
    hashes = {n: hashlib.sha256(c.encode("utf-8")).hexdigest() for n, c in csvs.items()}
    nlab = check_labels(figs, mac)
    if "--check" in sys.argv:
        for n, c in csvs.items():
            p = os.path.join(FIGS, n + "_data.csv")
            if not os.path.exists(p) or open(p, encoding="utf-8").read() != c:
                raise SystemExit("figures: %s_data.csv differs from a fresh regeneration" % n)
            pdf = os.path.join(FIGS, n + ".pdf")
            if not os.path.exists(pdf):
                raise SystemExit("figures: %s.pdf missing" % n)
            if ("csv-sha256=%s" % hashes[n]).encode() not in open(pdf, "rb").read():
                raise SystemExit("figures: %s.pdf was not built from the current %s_data.csv" % (n, n))
        print("figures: %d CSVs regenerate identically; %d printed values are macros; each PDF carries its CSV hash"
              % (len(csvs), nlab))
        return
    os.makedirs(FIGS, exist_ok=True)
    for n, c in csvs.items():
        with open(os.path.join(FIGS, n + "_data.csv"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(c)
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        print("matplotlib not installed: CSVs written, figures not regenerated (see requirements-figures.txt)")
        return
    plot(figs, mac, hashes)
    print("wrote %d figures and CSVs" % len(csvs))


if __name__ == "__main__":
    main()
