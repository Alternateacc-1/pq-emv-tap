"""EMV contactless transport: TLV sizes, APDU exchanges, ISO 14443-4 blocks,
Type A frames, and their timing.

Two independent evaluations of the same exchange list:
  closed_form()  - counts blocks/frames arithmetically per exchange
  simulate()     - builds every frame and gap as an event and walks them
They must agree exactly (hand calculation T12).

All times are fractions.Fraction seconds. EMV Level 1 v4.0 clauses are cited
in place; modelling choices D-P*, D-T1 and D-W1 are in docs/modelling_choices.md.
"""
from dataclasses import dataclass, field
from fractions import Fraction as F
from math import ceil

FC_BASE = 13_560_000          # D-P1
FDT_PICC = 1172               # 1/fc units, Table 4.2 n=9, last bit 0 (D-P4)
FDT_PICC_ALT = 1236           # last bit 1
FDT_PCD = 6780                # 1/fc units, Table A.6 PCD value (D-P4)
FWT_CARD = 4096 * 2 ** 7      # 1/fc units, FWI_MAX(card) = 7 (L1 Table A.6)
WTX_BLOCK = 4                 # S(WTX): PCB + 1-byte INF + CRC (L1 10.1)
RACK_BLOCK = 3                # R(ACK): PCB + CRC
BLOCK_OVERHEAD = 3            # PCB + CRC


def lenlen(n):
    """BER-TLV length-field size (Book 3 Annex B2)."""
    if n <= 127:
        return 1
    if n <= 255:
        return 2
    if n <= 65535:
        return 3
    raise ValueError(n)


def tlv(tag_len, value_len):
    return tag_len + lenlen(value_len) + value_len


@dataclass
class Link:
    fc: int = FC_BASE
    fsd: int = 256            # card->reader max block (D-P5)
    fsc: int = 256            # reader->card max block
    divisor: int = 1          # D-P2 (1 = EMV)
    fdt_picc: int = FDT_PICC
    fdt_pcd: int = FDT_PCD
    edc_excluded: bool = False

    @property
    def etu(self):
        return F(128, self.fc * self.divisor)

    def inf_max(self, frame):
        return frame - (1 if self.edc_excluded else BLOCK_OVERHEAD)

    def reader_frame(self, nbytes):   # D-P3
        return (9 * nbytes + 2) * self.etu

    def card_frame(self, nbytes):
        return (9 * nbytes + 1) * self.etu

    @property
    def t_fdt_picc(self):
        return F(self.fdt_picc, self.fc)

    @property
    def t_fdt_pcd(self):
        return F(self.fdt_pcd, self.fc)

    @property
    def fwt_card(self):
        return F(FWT_CARD, self.fc)

    def block_bytes(self, inf):
        return inf + BLOCK_OVERHEAD


@dataclass
class Exchange:
    """One C-APDU/R-APDU pair. `compute` names the card computation that
    runs after the last command block (None = none modelled)."""
    name: str
    c_len: int                 # C-APDU bytes
    r_len: int                 # R-APDU bytes (data + SW)
    compute: object = None


def split(total, size):
    n = max(1, ceil(total / size))
    parts = [size] * (n - 1) + [total - size * (n - 1)]
    return parts


# ---------------------------------------------------------------- closed form

@dataclass
class Totals:
    card_frames: F = F(0)      # card transmission (category 3)
    reader_frames: F = F(0)    # reader transmission (category 1)
    picc_gaps: int = 0         # number of FDT_A,PICC gaps without computation
    pcd_gaps: int = 0          # number of FDT_A,PCD gaps
    compute_slots: list = field(default_factory=list)   # compute keys, in order
    card_link_bytes: int = 0
    reader_link_bytes: int = 0
    card_apdu_bytes: int = 0
    reader_apdu_bytes: int = 0
    exchanges: int = 0


def closed_form(exchanges, link):
    t = Totals()
    ic, ir = link.inf_max(link.fsc), link.inf_max(link.fsd)
    for ex in exchanges:
        bc = ceil(ex.c_len / ic)
        br = ceil(ex.r_len / ir)
        oh = 1 if link.edc_excluded else BLOCK_OVERHEAD
        # reader: bc command blocks (sum 9*INF + 9*oh + 2 each) + (br-1) R(ACK)
        reader_etu = 9 * ex.c_len + bc * (9 * oh + 2) + (br - 1) * (9 * RACK_BLOCK + 2)
        card_etu = 9 * ex.r_len + br * (9 * oh + 1) + (bc - 1) * (9 * RACK_BLOCK + 1)
        t.reader_frames += reader_etu * link.etu
        t.card_frames += card_etu * link.etu
        reader_frames_n = bc + br - 1
        card_frames_n = br + bc - 1
        t.pcd_gaps += card_frames_n
        if ex.compute is None:
            t.picc_gaps += reader_frames_n
        else:
            t.picc_gaps += reader_frames_n - 1
            t.compute_slots.append(ex.compute)
        t.reader_link_bytes += ex.c_len + bc * oh + (br - 1) * RACK_BLOCK
        t.card_link_bytes += ex.r_len + br * oh + (bc - 1) * RACK_BLOCK
        t.reader_apdu_bytes += ex.c_len
        t.card_apdu_bytes += ex.r_len
        t.exchanges += 1
    return t


def wtx_count(t_c, window):
    """D-W1: n = max(0, ceil(T_c/W) - 1)."""
    if t_c <= window:
        return 0
    q = t_c / window
    return ceil(q) - 1


def wtx_parts(link):
    """(card seconds, reader seconds) per S(WTX) round trip."""
    return (link.card_frame(WTX_BLOCK),
            link.t_fdt_pcd + link.reader_frame(WTX_BLOCK))


def evaluate_closed(totals, link, compute_times, pause=True):
    """compute_times: dict key -> seconds. Returns tariff times."""
    wc, wr = wtx_parts(link)
    card = totals.card_frames + totals.picc_gaps * link.t_fdt_picc
    reader = totals.reader_frames + totals.pcd_gaps * link.t_fdt_pcd
    wtx = []
    for key in totals.compute_slots:
        tc = compute_times[key]
        n = wtx_count(tc, link.fwt_card)
        wtx.append(n)
        card += max(link.t_fdt_picc, tc)
        if pause:
            card += n * wc
            reader += n * wr
    return {"card": card, "reader": reader, "wtx": wtx}


# ---------------------------------------------------------------- simulation

def frames_of(ex, link):
    """Explicit frame sequence of one exchange: list of (side, block_bytes)."""
    ic, ir = link.inf_max(link.fsc), link.inf_max(link.fsd)
    oh = 1 if link.edc_excluded else BLOCK_OVERHEAD
    seq = []
    cparts = split(ex.c_len, ic)
    for i, p in enumerate(cparts):
        seq.append(("reader", p + oh, i == len(cparts) - 1))
        if i < len(cparts) - 1:
            seq.append(("card", RACK_BLOCK, False))
    rparts = split(ex.r_len, ir)
    for i, p in enumerate(rparts):
        seq.append(("card", p + oh, False))
        if i < len(rparts) - 1:
            seq.append(("reader", RACK_BLOCK, False))
    return seq


def simulate(exchanges, link, compute_times, pause=True):
    """Walk every frame and gap in time order, attributing each to a tariff
    (D-T1). Returns the same keys as evaluate_closed plus event counts."""
    card = F(0)
    reader = F(0)
    wtx = []
    events = 0
    for ex in exchanges:
        for side, nbytes, last_cmd in frames_of(ex, link):
            events += 1
            if side == "reader":
                reader += link.reader_frame(nbytes)
                if last_cmd and ex.compute is not None:
                    remaining = compute_times[ex.compute]
                    n = 0
                    elapsed = F(0)
                    while remaining > link.fwt_card:
                        # card computes one full window, then S(WTX) exchange
                        elapsed += link.fwt_card
                        remaining -= link.fwt_card
                        n += 1
                        if pause:
                            card += link.card_frame(WTX_BLOCK)
                            reader += link.t_fdt_pcd
                            reader += link.reader_frame(WTX_BLOCK)
                        events += 2
                    elapsed += remaining
                    card += max(link.t_fdt_picc, elapsed)
                    wtx.append(n)
                else:
                    card += link.t_fdt_picc
            else:
                card += link.card_frame(nbytes)
                reader += link.t_fdt_pcd
    return {"card": card, "reader": reader, "wtx": wtx, "events": events}
