"""A second, independent implementation of the timing model.

It does not import pqemv. It rebuilds the message flows from the rules in
docs/modelling_choices.md, times every frame and frame delay with exact fractions,
and compares about thirty headline values with the macros in
paper/numbers.tex (the numbers printed in the paper).

Run: python checks/independent_model.py
"""
import os
import re
import sys
from fractions import Fraction as F
from math import ceil

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

FC = 13_560_000
ETU = F(128, FC)                 # one bit at 106 kbit/s
T_PICC = F(1172, FC)             # card turnaround (card time)
T_PCD = F(6780, FC)              # reader frame delay, 0.5 ms (reader time)
FWT = F(4096 * 2 ** 7, FC)       # card waiting time, FWI 7
T_P = F(51, 10_000)              # polling wait, 5.1 ms
READER, CARD = F(1, 10), F(4, 10)

SIG = {"ML-DSA-44": (1312, 2420), "ML-DSA-65": (1952, 3309), "ML-DSA-87": (2592, 4627),
       "FN-DSA-512": (897, 666), "FN-DSA-1024": (1793, 1280)}
KEM = {"ML-KEM-512": (800, 768), "ML-KEM-768": (1184, 1088), "ML-KEM-1024": (1568, 1568)}


def L(n):
    return 1 if n < 128 else 2 if n < 256 else 3


def tlv(tag, n):
    return tag + L(n) + n


def rec(n):
    return tlv(1, n)


class Flow:
    """Times one list of APDU exchanges, split into reader and card time."""

    def __init__(self, frame=256, divisor=1):
        self.inf = frame - 3                     # PCB + CRC per block
        self.etu = ETU / divisor
        self.reader_tx = self.card_tx = F(0)
        self.pcd_gaps = self.picc_gaps = 0
        self.compute = []

    def reader_frame(self, n):
        """Type A reader frame of n bytes: start, 9 etu per byte, end."""
        return (9 * n + 2) * self.etu

    def apdu(self, c, r, compute=None):
        cb = [self.inf] * (ceil(c / self.inf) - 1)
        cb.append(c - sum(cb))
        rb = [self.inf] * (ceil(r / self.inf) - 1)
        rb.append(r - sum(rb))
        seq = []
        for i, b in enumerate(cb):
            seq.append(("R", b + 3))
            if i < len(cb) - 1:
                seq.append(("C", 3))             # R(ACK) from the card
        for i, b in enumerate(rb):
            seq.append(("C", b + 3))
            if i < len(rb) - 1:
                seq.append(("R", 3))             # R(ACK) from the reader
        first_response = 2 * len(cb) - 1
        for k, (side, n) in enumerate(seq):
            if side == "R":
                self.reader_tx += self.reader_frame(n)
            else:
                self.card_tx += (9 * n + 1) * self.etu
                if compute is not None and k == first_response:
                    self.compute.append(compute)
                else:
                    self.picc_gaps += 1
                self.pcd_gaps += 1

    def reader(self):
        return self.reader_tx + self.pcd_gaps * T_PCD

    def card_fixed(self):
        return self.card_tx + (self.picc_gaps + len(self.compute)) * T_PICC


def read_cert(f, cert):
    for i in range(ceil(cert / 247)):
        f.apdu(5, rec(tlv(2, min(247, cert - 247 * i))) + 2)


def certs(f, pk, sig, key, depth):
    if depth == 2:
        f.apdu(5, rec(3) + 2)
        read_cert(f, 21 + pk + sig)
    read_cert(f, 17 + 32 + key + sig)


def pieces(f, c, data, compute=None):
    f.apdu(c, min(256, data) + 2, compute)
    for i in range(1, max(1, ceil(data / 256))):
        f.apdu(5, min(256, data - 256 * i) + 2)


def chain(f, data, compute):
    n = ceil(data / 255)
    for i in range(n):
        f.apdu(5 + min(255, data - 255 * i), 2, compute if i == n - 1 else None)


def arch_a(s, depth=2, frame=256, divisor=1):
    pk, sg = SIG[s]
    f = Flow(frame, divisor)
    certs(f, pk, sg, pk, depth)
    pieces(f, 46, tlv(1, 9 + tlv(2, sg)), "sign")
    return f


def arch_b(s, depth=2):
    pk, sg = SIG[s]
    f = Flow()
    pieces(f, 4 + 1 + tlv(1, 16) + 1, tlv(1, 10 + tlv(2, sg)), "sign")
    certs(f, pk, sg, pk, depth)
    return f


def c_min(s, k, depth=2, frame=256, divisor=1):
    pk, sg = SIG[s]
    ek, ct = KEM[k]
    f = Flow(frame, divisor)
    f.apdu(5 + tlv(1, 8) + 1, tlv(1, 10) + 2)
    certs(f, pk, sg, ek, depth)
    chain(f, ct, "decaps")
    return f


def c_priv(s, k, depth=2, frame=256, divisor=1):
    pk, sg = SIG[s]
    ek, ct = KEM[k]
    f = Flow(frame, divisor)
    g = tlv(1, ek + 8)
    n = ceil(g / 255)
    for _ in range(n - 1):
        f.apdu(5 + 255, 2)
    pieces(f, 5 + g - 255 * (n - 1) + 1, tlv(1, 10 + tlv(3, ct)), "encaps")
    certs(f, pk, sg, ek, depth)
    chain(f, ct, "decaps")
    return f


def r_min():
    """Mandatory rest of a Kernel 8 transaction (reader side), by hand."""
    etu_frames = (9 * 4 + 2) + 9 + (9 * 2 + 2) + (9 * 9 + 2) + (9 * 4 + 2) \
        + (9 * 23 + 2) + (9 * 14 + 2) + (9 * 8 + 2)        # HLTA..GENERATE AC
    wupb = F(1280 + 248, FC) + 50 * ETU + F(1280, FC)
    return etu_frames * ETU + wupb + 7 * T_PCD


def sign_budget_cycles(flow, clock):
    """Largest signing cycle count that keeps card time within 400 ms."""
    fixed = flow.card_fixed() - T_PICC
    wtx = (9 * 4 + 1) * flow.etu                          # card's S(WTX) frame
    lo, hi = 0, 10 ** 9
    while lo < hi:
        mid = (lo + hi + 1) // 2
        t = F(mid, clock)
        n = 0 if t <= FWT else ceil(t / FWT) - 1
        if fixed + max(T_PICC, t) + n * wtx <= CARD:
            lo = mid
        else:
            hi = mid - 1
    return lo


def macros():
    text = open(os.path.join(ROOT, "paper", "numbers.tex"), encoding="utf-8").read()
    out = {}
    for name, val in re.findall(r"\\newcommand\{\\(\w+)\}\{(.*)\}%", text):
        out[name] = val.replace("\\,", "").replace("\\ensuremath{-}", "-")
    return out


def r(x, nd):
    q = F(10) ** nd
    v = (abs(x) * q + F(1, 2)).__floor__()
    s = "%d" % v
    if nd:
        s = s.rjust(nd + 1, "0")
        s = s[:-nd] + "." + s[-nd:]
    return ("-" if x < 0 else "") + s


def main():
    M = macros()
    ms = lambda x: x * 1000
    rows = []

    def check(label, mine, macro):
        printed = M[macro]
        rows.append((label, mine, printed, mine == printed))

    a = c_min("FN-DSA-512", "ML-KEM-512")
    check("C-min FN-512/K-512 reader transmission, ms", r(ms(a.reader_tx), 3), "CminFnFiveKemFiveTxMs")
    check("  its frame delays, ms", r(ms(a.pcd_gaps * T_PCD), 1), "CminFnFiveKemFiveGapsMs")
    a5 = c_min("FN-DSA-512", "ML-KEM-512", frame=512)
    check("C-min FN-512/K-512, 512-byte frames, ms", r(ms(a5.reader()), 3), "FnineAuthMs")
    check("R_min, ms", r(ms(r_min()), 3), "RminMs")
    left = READER - a5.reader() - r_min()
    check("margin without waits, ms", r(ms(left), 3), "FnineMarginMs")
    check("margin with both waits, ms", r(ms(left - 2 * T_P), 3), "FnineMarginTpMs")
    check("reader clock without waits, MHz", r(F(ceil(F(1184779) / left), 10 ** 6), 1), "FnineClockMHz")
    n = sum(1 for s in SIG for k in KEM for fn in (c_min, c_priv) if fn(s, k).reader_tx > READER)
    check("Kernel 8-style designs over 100 ms on transmission", str(n), "CTxOnlyExceed")
    check("C-priv FN-512/K-512 transmission, ms", r(ms(c_priv("FN-DSA-512", "ML-KEM-512").reader_tx), 3), "CprivFnFiveKemFiveTxMs")
    check("C-priv FN-512/K-512 reader time, ms", r(ms(c_priv("FN-DSA-512", "ML-KEM-512").reader()), 1), "CprivReaderMs")
    check("  same at D = 4, ms", r(ms(c_priv("FN-DSA-512", "ML-KEM-512", divisor=4).reader()), 1), "CprivReaderDFourMs")
    d1 = c_min("FN-DSA-512", "ML-KEM-512", depth=1, frame=512)
    check("depth 1, 512-byte frames, margin with waits, ms", r(ms(READER - d1.reader() - r_min() - 2 * T_P), 3), "FfifteenBestTpMs")
    cards = {s: (arch_a(s).card_fixed(), arch_b(s).card_fixed()) for s in SIG}
    check("A ML-DSA-44 card time, ms", r(ms(cards["ML-DSA-44"][0]), 1), "AMlFourCardFloorMs")
    lo = min(v[0] for s, v in cards.items() if s != "FN-DSA-512")      # the paper quotes A;
    hi = max(v[0] for s, v in cards.items() if s != "FN-DSA-512")      # B is within 0.1 ms
    gap = max(v[1] - v[0] for v in cards.values())
    rows.append(("B minus A, largest difference, ms", r(ms(gap), 3), "< 0.1", 0 < gap < F(1, 10000)))
    check("A/B card time, low end, ms", r(ms(lo), 1), "FsevenCardLoMs")
    check("A/B card time, high end, ms", r(ms(hi), 1), "FsevenCardHiMs")
    check("A FN-DSA-512 card time, ms", r(ms(cards["FN-DSA-512"][0]), 1), "AFnFiveCardMs")
    fields = [arch_a(s).card_fixed() + arch_a(s).reader() - T_PCD for s in SIG if s != "FN-DSA-512"] + \
             [arch_b(s).card_fixed() + arch_b(s).reader() for s in SIG if s != "FN-DSA-512"]
    check("card + reader, low end, ms", r(ms(min(fields)), 1), "FsevenFieldLoMs")
    check("card + reader, high end, ms", r(ms(max(fields)), 1), "FsevenFieldHiMs")
    check("A ML-DSA-44 depth 1 card time, ms (lower bound)", r(ms(arch_a("ML-DSA-44", depth=1).card_fixed()) - F(5, 100), 1), "AMlFourDepthOneCardMs")
    check("A ML-DSA-44 at D = 4, ms", r(ms(arch_a("ML-DSA-44", divisor=4).card_fixed()), 1), "AMlFourDFourCardMs")
    check("A FN-DSA-1024 at D = 2, ms", r(ms(arch_a("FN-DSA-1024", divisor=2).card_fixed()), 1), "AFnTenDTwoCardMs")
    rd = [arch_b("ML-DSA-65").reader(), arch_a("ML-DSA-87").reader() - T_PCD]
    check("ML-DSA-65/87 reader time, low, ms", r(ms(min(rd)), 1), "FsixReaderLoMs")
    check("ML-DSA-65/87 reader time, high, ms", r(ms(max(rd)), 1), "FsixReaderHiMs")
    cyc = sign_budget_cycles(arch_a("FN-DSA-512"), 80_000_000)
    check("FN-DSA-512 signing budget at 80 MHz, cycles", str(cyc), "FtenMaxCycles")

    width = max(len(x[0]) for x in rows)
    bad = 0
    for label, mine, printed, ok in rows:
        bad += not ok
        print("%-*s  mine %-12s paper %-12s %s" % (width, label, mine, printed, "ok" if ok else "DIFFERENT"))
    print("\n%d of %d values agree with paper/numbers.tex" % (len(rows) - bad, len(rows)))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
