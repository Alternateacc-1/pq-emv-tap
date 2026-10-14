"""Sharing records between certificates.

The model puts the CA key index in a record of its own and starts each
certificate in a new record. EMV Book 3 section 7.1 lets one record hold
several data objects (the classical Kernel 8 layout already shares one).
This packs the index and both certificates into the fewest 254-byte
records and recomputes the affected results. Everything else is the model
in pqemv/, unchanged.

Run: python checks/record_packing.py
"""
import os, sys
from fractions import Fraction as F
from math import ceil
REPO = sys.argv[1] if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]) else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, REPO); sys.path.insert(0, os.path.join(REPO, "analyses")); os.chdir(REPO)
import run as R
from pqemv import architectures as ar
from pqemv.transport import Link, closed_form, lenlen
import kernel8_rmin as S

CAP = ar.RECORD_MAX - 3          # '70' + 2-byte length -> 251 bytes of content

def need(cond, what):
    """Stop with a message when a check fails (works under python -O too)."""
    if not cond:
        raise SystemExit("check failed: %r" % (what,))



def packed_contents(cert_lengths, ca_index=True):
    """Fewest records: greedy fill; certificates may be split anywhere."""
    recs, cur = [], (3 if ca_index else 0)      # '8F' 01 xx
    for n in cert_lengths:
        rem = n
        while rem:
            space = CAP - cur
            if space < 4:                       # no room for a tag + length + 1 byte
                recs.append(cur); cur = 0; continue
            f = min(rem, space - 2 - (2 if space - 4 >= 128 else 1))
            f = min(rem, f)
            cur += 2 + lenlen(f) + f
            rem -= f
            if CAP - cur < 4:
                recs.append(cur); cur = 0
    if cur:
        recs.append(cur)
    return recs


def packed_cert_exchanges(sig, icc_key_len, depth, fmt="E"):
    certs = ([ar.pq_issuer_cert(sig, fmt)] if depth == 2 else []) + [ar.pq_icc_cert(sig, icc_key_len, fmt)]
    contents = packed_contents(certs, ca_index=(depth == 2))
    for c in contents:
        need(ar.record(c) <= ar.RECORD_MAX, "check failed")
    return [ar.read_record("packed rec %d" % i, ar.record(c)) for i, c in enumerate(contents)]


orig = ar.cert_exchanges


def patched(sig, icc_key_len, depth, fmt, extended):
    if extended:
        return orig(sig, icc_key_len, depth, fmt, extended)
    return packed_cert_exchanges(sig, icc_key_len, depth, fmt)


ETU = F(128, 13_560_000)
frames = sum((S.wupb_time() if n.startswith("WUPB") else e * ETU) for n, b, e, g, c, k in S.TERMS if not n.startswith("t_P"))
gaps = sum(g for n, b, e, g, c, k in S.TERMS if not n.startswith("t_P")) * S.GAP
RMIN = frames + gaps


def reader_card(arch, sig, kem, fs=256):
    ex, _, rops = R.build(arch, sig, kem, 2)
    link = Link(fsd=fs, fsc=fs)
    tot = closed_form(ex, link)
    rd = tot.reader_frames + tot.pcd_gaps * link.t_fdt_pcd
    _, card0, _ = R.fixed_times(ex, link)
    nrec = sum(1 for e in ex if e.name.startswith(("CA index", "issuer cert", "ICC cert", "packed")))
    return rd, card0, tot.reader_frames, nrec, rops


def main():
    rows = []
    for label in ("model", "packed"):
        ar.cert_exchanges = orig if label == "model" else patched
        res = {}
        for arch in ("C-min", "C-priv"):
            for sig in ("ML-DSA-44", "ML-DSA-65", "ML-DSA-87", "FN-DSA-512", "FN-DSA-1024"):
                for kem in ("ML-KEM-512", "ML-KEM-768", "ML-KEM-1024"):
                    res[(arch, sig, kem, 256)] = reader_card(arch, sig, kem)
        res[("C-min", "FN-DSA-512", "ML-KEM-512", 512)] = reader_card("C-min", "FN-DSA-512", "ML-KEM-512", 512)
        for arch in ("A", "B"):
            for sig in ("ML-DSA-44", "ML-DSA-65", "ML-DSA-87", "FN-DSA-512", "FN-DSA-1024"):
                res[(arch, sig, None, 256)] = reader_card(arch, sig, None)
        rows.append((label, res))

    m, p = rows[0][1], rows[1][1]
    n_tx_m = sum(1 for k, v in m.items() if k[0].startswith("C") and k[3] == 256 and v[2] > R.READER_BUDGET)
    n_tx_p = sum(1 for k, v in p.items() if k[0].startswith("C") and k[3] == 256 and v[2] > R.READER_BUDGET)
    print("Kernel 8-style configs whose reader transmission alone > 100 ms: model %d/30, packed %d/30" % (n_tx_m, n_tx_p))
    for k in [("C-min", "FN-DSA-512", "ML-KEM-512", 256), ("C-min", "ML-DSA-44", "ML-KEM-512", 256),
              ("C-min", "FN-DSA-1024", "ML-KEM-512", 256), ("C-priv", "FN-DSA-512", "ML-KEM-512", 256),
              ("C-min", "FN-DSA-512", "ML-KEM-512", 512)]:
        print("%-40s records %d -> %d | reader tx %s -> %s | tx+delays %s -> %s ms"
              % (k, m[k][3], p[k][3], R.ms(m[k][2]), R.ms(p[k][2]), R.ms(m[k][0]), R.ms(p[k][0])))
    k = ("C-min", "FN-DSA-512", "ML-KEM-512", 512)
    for lab, d in (("model", m), ("packed", p)):
        left_tp = R.READER_BUDGET - d[k][0] - RMIN - 2 * S.T_P
        left_no = R.READER_BUDGET - d[k][0] - RMIN
        print("%s: margin with R_min + both waits %s ms; without waits %s ms -> %s MHz (2 verify+encaps) / %s MHz (encaps only)"
              % (lab, R.ms(left_tp), R.ms(left_no), R.mhz(ceil(F(1184779) / left_no)), R.mhz(ceil(F(390881) / left_no))))
    print("signing designs (card fixed ms, model -> packed):")
    for sig in ("ML-DSA-44", "ML-DSA-65", "ML-DSA-87", "FN-DSA-512", "FN-DSA-1024"):
        for arch in ("A", "B"):
            kk = (arch, sig, None, 256)
            print("  %s %-11s records %d -> %d  card %s -> %s  reader %s -> %s"
                  % (arch, sig, m[kk][3], p[kk][3], R.ms(m[kk][1]), R.ms(p[kk][1]), R.ms(m[kk][0]), R.ms(p[kk][0])))
    # FN-DSA-512 card compute budget at 80 MHz (same S(WTX) logic as run.py)
    link = Link()
    for label, fn in (("packed", patched), ("model", orig)):
        ar.cert_exchanges = fn
        ex, _, _ = R.build("A", "FN-DSA-512", None, 2)
        lo, hi = 1, 50_000_000
        while lo < hi:                       # largest cycle count meeting 400 ms at 80 MHz
            mid = (lo + hi + 1) // 2
            _, a = R.evaluate(ex, link, {("sign",): mid}, 80_000_000)
            if a["card"] <= R.CARD_BUDGET: lo = mid
            else: hi = mid - 1
        print("A FN-DSA-512 max signing cycles at 80 MHz (%s): %d; Pornin 13.45M needs >= %s MHz" % (label, lo, R.mhz(R.required_clock(ex, link, {("sign",): 13_450_000}, R.CARD_BUDGET))))


if __name__ == "__main__":
    main()
