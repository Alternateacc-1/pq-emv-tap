"""Type B cards.

The model times Type A frames. A Type B card sends 10-etu characters (start
bit, 8 data bits, stop bit; L1 4.7), its frames add a start and end of
sequence, the reader's minimum frame delay is the same 6780/fc (L1 Annex A.4,
FDT_B,PCD,MIN), and the polling procedure still has a t_P wait before WUPA
(L1 9.2.1.3) and before WUPB (L1 9.3.3.1) after the card is found. This
re-times the C-min reader side with Type B frames at their minimum sizes.

Run: python checks/type_b.py
"""
import os
import sys
from fractions import Fraction as F

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import independent_model as M                          # noqa: E402

SOS, EOS = F(1280 + 248, M.FC), F(1280, M.FC)        # PCD minima, L1 Annex A.4


class FlowB(M.Flow):
    def reader_frame(self, n):
        """Type B reader frame: start of sequence, 10 etu per character, end of sequence."""
        return SOS + 10 * n * self.etu + EOS


def c_min_b(frame):
    f = FlowB(frame)
    f.apdu(5 + M.tlv(1, 8) + 1, M.tlv(1, 10) + 2)
    M.certs(f, 897, 666, 800, 2)
    M.chain(f, 768, "decaps")
    return f


def main():
    for frame in (256, 512):
        a = M.c_min("FN-DSA-512", "ML-KEM-512", frame=frame)
        b = c_min_b(frame)
        print("C-min FN-DSA-512/ML-KEM-512, %d-byte frames: authentication exchanges, reader time "
              "Type A %.3f ms, Type B %.3f ms" % (frame, float(a.reader() * 1000), float(b.reader() * 1000)))


if __name__ == "__main__":
    main()
