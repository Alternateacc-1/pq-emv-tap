"""Message flows of the four architectures, classical and post-quantum:
A (Kernel 2, CDA), B (Kernel 3, fDDA), C-min and C-priv (Kernel 8 style).

Each builder returns (exchanges, card_ops, reader_ops). The choices behind
the flows (D-T2, D-T3, D-K1, D-K2, D-C1 to D-C4, D-R1, D-R2, D-S1, D-S2) are
explained in docs/modelling_choices.md.
"""
from math import ceil

from .transport import Exchange, tlv

RECORD_MAX = 254          # Book 3 §7.1
RESP_MAX = 256            # Book 1 §11.1.1
CMD_MAX = 255             # Book 2 D1 (command data)
FRAG_TAG = 2              # D-C2 new 2-byte fragment tags
CDOL1_LEN = 40            # D-T3 (Book E Table 3.1)
PDOL_B_LEN = 16           # D-T3 (C-3 Table C-1 + TTQ)
PDOL_C_LEN = 72           # D-T3 (Kernel Key Data 64 + Kernel Qualifier 8)
KQ_LEN = 8
AIP_TLV = 4               # '82' 02 xx xx
AFL_TLV = 6               # '94' 04 + one entry
CID_TLV = 4               # '9F27' 01 xx
ATC_TLV = 5               # '9F36' 02 xx xx


def record(inner):
    """A '70' record around TLV content of `inner` bytes."""
    return tlv(1, inner)


def max_fragment():
    f = 1
    while record(tlv(FRAG_TAG, f + 1)) <= RECORD_MAX:
        f += 1
    return f


FRAG = max_fragment()     # 247 (TESTS T08)


def read_record(name, rec_len):
    if rec_len > RECORD_MAX:
        raise ValueError("record over 254 bytes: %s (%d)" % (name, rec_len))
    return Exchange(name, 5, rec_len + 2)


def cert_records(prefix, cert_len):
    n = ceil(cert_len / FRAG)
    out = []
    for i in range(n):
        frag = min(FRAG, cert_len - FRAG * i)
        out.append(read_record("%s rec %d/%d" % (prefix, i + 1, n), record(tlv(FRAG_TAG, frag))))
    return out


def cert_extended(prefix, cert_len):
    # D-R2: one extended-length exchange; C-APDU 4 + '00' Le1 Le2 = 7
    return [Exchange("%s (extended)" % prefix, 7, tlv(FRAG_TAG, cert_len) + 2)]


def response_pieces(name, c_first, data_len, compute, extended, c_first_ext=None):
    """D-S1: data > 256 returned in 256-byte pieces via GET RESPONSE."""
    if extended:
        return [Exchange(name + " (extended)", c_first_ext, data_len + 2, compute)]
    n = max(1, ceil(data_len / RESP_MAX))
    ex = [Exchange(name, c_first, min(RESP_MAX, data_len) + 2, compute)]
    for i in range(1, n):
        piece = min(RESP_MAX, data_len - RESP_MAX * i)
        ex.append(Exchange("GET RESPONSE %d/%d" % (i + 1, n), 5, piece + 2))
    return ex


def command_chain(name, data_len, compute, le, extended, response_len=2):
    """D-S2: command data > 255 bytes by ISO/IEC 7816-4 command chaining.
    The final C-APDU carries Le if `le`; its response is `response_len`
    bytes (data + SW); intermediate responses are SW only."""
    if extended:
        c = 4 + 3 + data_len + (2 if le else 0)
        return [Exchange(name + " (extended)", c, response_len, compute)]
    n = max(1, ceil(data_len / CMD_MAX))
    out = []
    for i in range(n):
        chunk = min(CMD_MAX, data_len - CMD_MAX * i)
        last = i == n - 1
        c = 4 + 1 + chunk + (1 if (last and le) else 0)
        out.append(Exchange("%s %d/%d" % (name, i + 1, n), c,
                            response_len if last else 2,
                            compute if last else None))
    return out


# ------------------------------------------------------------ certificates

def pq_issuer_cert(sig, fmt):
    pk, s = sig["pk"], sig["sig"]
    return (21 if fmt == "E" else 14) + pk + s          # D-C1 / D-C1b


def pq_icc_cert(sig, key_len, fmt):
    return (17 + 32 if fmt == "E" else 20) + key_len + sig["sig"]


def cert_exchanges(sig, icc_key_len, depth, fmt, extended):
    ex = []
    if depth == 2:
        ex.append(read_record("CA index '8F'", record(3)))
        ic = pq_issuer_cert(sig, fmt)
        ex += cert_extended("issuer cert", ic) if extended else cert_records("issuer cert", ic)
    cc = pq_icc_cert(sig, icc_key_len, fmt)
    ex += cert_extended("ICC cert", cc) if extended else cert_records("ICC cert", cc)
    return ex


# ------------------------------------------------------------ classical

RSA = {"NCA": 248, "NI": 247, "NIC": 239, "e_len": 1}      # D-K1


def classical_rsa_records(depth):
    NCA, NI, NIC, e = RSA["NCA"], RSA["NI"], RSA["NIC"], RSA["e_len"]
    ex = []
    if depth == 2:
        ex.append(read_record("issuer cert '90'", record(tlv(1, NCA))))
    ex.append(read_record("ICC cert '9F46'", record(tlv(2, NI))))
    icc_rem = NIC - NI + 42
    misc = tlv(2, icc_rem) + tlv(2, e)                     # '9F48', '9F47'
    if depth == 2:
        iss_rem = NI - NCA + 36
        misc += tlv(1, 1) + tlv(1, iss_rem) + tlv(2, e)    # '8F', '92', '9F32'
    ex.append(read_record("remainders/exponents", record(misc)))
    return ex


def arch_A(sig, depth, fmt="E", extended=False, classical=False):
    """Kernel 2 CDA: card signs in GENERATE AC."""
    if classical:
        s_len = RSA["NIC"]
        ex = classical_rsa_records(depth)
    else:
        s_len = sig["sig"]
        ex = cert_exchanges(sig, sig["pk"], depth, fmt, extended)
    data = tlv(1, CID_TLV + ATC_TLV + tlv(2, s_len))        # '77' [...]
    c_short = 4 + 1 + CDOL1_LEN + 1
    c_ext = 4 + 3 + CDOL1_LEN + 2
    ex += response_pieces("GENERATE AC", c_short, data, None if classical else ("sign",), extended and not classical, c_ext)
    card_ops = [] if classical else [("sign",)]
    reader_ops = [] if classical else [("verify",)] * (3 if depth == 2 else 2)
    return ex, card_ops, reader_ops


def arch_B(sig, depth, fmt="E", extended=False, classical=False):
    """Kernel 3 fDDA: card signs in GPO; certificates in later records."""
    s_len = RSA["NIC"] if classical else sig["sig"]
    data = tlv(1, AIP_TLV + AFL_TLV + tlv(2, s_len))
    gpo_cmd = tlv(1, PDOL_B_LEN)                           # '83' L data
    c_short = 4 + 1 + gpo_cmd + 1
    c_ext = 4 + 3 + gpo_cmd + 2
    ex = response_pieces("GPO", c_short, data, None if classical else ("sign",), extended and not classical, c_ext)
    ex += classical_rsa_records(depth) if classical else cert_exchanges(sig, sig["pk"], depth, fmt, extended)
    card_ops = [] if classical else [("sign",)]
    reader_ops = [] if classical else [("verify",)] * (3 if depth == 2 else 2)
    return ex, card_ops, reader_ops


def arch_C_classical(depth):
    gpo_cmd = tlv(1, PDOL_C_LEN)
    ex = [Exchange("GPO", 4 + 1 + gpo_cmd + 1, tlv(1, AIP_TLV + AFL_TLV + tlv(3, 64)) + 2)]
    if depth == 2:
        ex.append(read_record("issuer cert '90'", record(tlv(1, 1) + tlv(1, 117))))
    ex.append(read_record("ICC cert '9F46'", record(tlv(2, 145))))
    return ex, [], []


def arch_C_min(sig, kem, depth, fmt="E", extended=False):
    """D-C3: GPO without key data; certificates in clear; ESTABLISH carries
    the reader's encapsulation; card decapsulates."""
    gpo_cmd = tlv(1, KQ_LEN)
    ex = [Exchange("GPO", 4 + 1 + gpo_cmd + 1, tlv(1, AIP_TLV + AFL_TLV) + 2)]
    ex += cert_exchanges(sig, kem["ek"], depth, fmt, extended)
    ex += command_chain("ESTABLISH", kem["ct"], ("decaps",), le=False, extended=extended)
    card_ops = [("decaps",)]
    reader_ops = [("verify",)] * (2 if depth == 2 else 1) + [("encaps",)]
    return ex, card_ops, reader_ops


def arch_C_priv(sig, kem, depth, fmt="E", extended=False):
    """D-C4: ephemeral reader KEM key in GPO (card encapsulates), encrypted
    certificates, ESTABLISH with the static-key ciphertext (card decapsulates)."""
    gpo_cmd = tlv(1, kem["ek"] + KQ_LEN)
    resp = tlv(1, AIP_TLV + AFL_TLV + tlv(3, kem["ct"]))
    if extended:
        ex = [Exchange("GPO (extended)", 4 + 3 + gpo_cmd + 2, resp + 2, ("encaps",))]
    else:
        ex = command_chain("GPO", gpo_cmd, None, le=True, extended=False)
        last = ex[-1]
        pieces = response_pieces("GPO", last.c_len, resp, ("encaps",), False)
        ex = ex[:-1] + pieces
    ex += cert_exchanges(sig, kem["ek"], depth, fmt, extended)
    ex += command_chain("ESTABLISH", kem["ct"], ("decaps",), le=False, extended=extended)
    card_ops = [("encaps",), ("decaps",)]
    reader_ops = [("keygen",), ("decaps",)] + [("verify",)] * (2 if depth == 2 else 1) + [("encaps",)]
    return ex, card_ops, reader_ops
