# Modelling choices

This page lists every choice the model makes, why, and what the alternatives
would change. The code refers to each choice by its label (D-P1, D-T1, ...).
The other labels used in the code are:

- **T01–T13**: values worked out by hand, in `hand_calculations.md`;
- **F1–F15**: the findings of the paper (table at the end);
- **E1–E7**: corrections made during the analysis (table at the end).

Specification clauses are cited as, for example, "L1 4.8.2.1" (EMV Level 1
Contactless Interface v4.0) or "Book A 10.2.1.1" (EMV Contactless Book A
v2.12). Short keys such as P26 or GKS21 name the papers listed at the end.

## Physical layer

### D-P1 Carrier frequency
Baseline fc = 13 560 000 Hz, the midpoint of Table A.2's range (13.553–13.567
MHz). Alternative: the two ends. All results are exact functions of fc; the
range moves every transmission time by less than ±0.052 %. Reported once
in the sensitivity results, not per configuration.

### D-P2 Bit rate
Baseline fc/128 (≈106 kbit/s) both directions (L1 4.2.1.1, 5.7.2.9, 5.8.1.1).
Alternative (out of specification): D = 2, 4, 8, applied to both
directions by dividing the etu; frame delay times are kept at their fc/128
values (the higher-rate FDT rules are not quoted here). Reported as a
sensitivity only, labelled "outside EMV L1 v4.0".

### D-P3 Frame bit counts (Type A)
Reader→card frame of n bytes: 9n + 2 etu (SoF, n × (8 + parity), EoF).
Card→reader frame: 9n + 1 etu (SoF, n × 9; no EoF) (L1 4.7.1). Sub-etu
effects ignored (≤ 1 etu per frame; recorded tolerance). Type B is not
modelled: EMV cards may be A or B; Type A is the only type whose per-byte
cost is fully specified for both sides. `checks/type_b.py` shows that Type B
frames only make the reader's times longer.

### D-P4 Frame delay times
After each reader frame the card's frame starts FDT_A,PICC = 1172/fc later
(Table 4.2, n = 9, last bit "0"; the minimum grid position), unless the card
computes, in which case the gap is the computation time (D-W1). Alternative:
1236/fc (last bit "1"); moves card time by 64/fc per card frame.
After each card frame the reader's next frame starts FDT_A,PCD,MIN = 6780/fc
later (PCD value, 4.8.2.1) — the minimum a compliant reader must wait.
Both are lower bounds on real gaps.

### D-P5 Block and frame size
Block = PCB (1) + INF + CRC (2) (L1 §10.1; CID/NAD unused). The whole block
counts against FSD/FSC (reading of §10.1.1). Baseline FSD = FSC = 256 bytes,
INF ≤ 253 per block. Alternatives (sensitivity): FSD = FSC = 1024 and 4096 (Table 5.14
maximum 'C'); and the EDC-excluded reading (INF ≤ 255 at FSD 256).
Chaining (§10.3.2): each chained block is acknowledged by a 3-byte R(ACK)
from the other side.

## Tariff accounting

### D-T1 Assignment of gaps
Book A §10.2 assigns transmissions and processing to five categories but
does not name frame-delay gaps. Baseline: FDT_A,PICC (and card computation)
→ card tariff (category 2, card processing); FDT_A,PCD → reader tariff
(category 4, reader processing). Alternative D-T1b: gaps assigned to neither
tariff (they still count in card-in-field time). Both reported.

### D-T2 Scope of "authentication data"
The model counts only the APDU exchanges that authentication requires or
changes, in full (header, data, SW, blocks, frames, gaps):
- A (Kernel 2 CDA): the GENERATE AC exchange; READ RECORD of every record
  holding authentication objects; follow-up exchanges needed to fetch a
  PQ signature.
- B (Kernel 3 fDDA): the GPO exchange; the authentication records; follow-ups.
- C (Kernel 8): the GPO exchange; the certificate records; any new PQ
  exchange. GENERATE AC is excluded: EDA-MAC and all other GENERATE AC
  content are identical in the classical and PQ forms.
All other exchanges (activation, SELECT, PAN/track records, CVM, …) are
excluded. Every figure is therefore a **lower bound** on the tariff use.
Card and reader computation outside the PQ primitives (MACs, AC, hashes of
static data, RSA/ECC operations in the classical forms) is not modelled:
no input source gives it for these chips.

### D-T3 Non-authentication fields inside modelled exchanges
- GENERATE AC command data (A): 40 bytes, the Book E Table 3.1 recommended
  CDOL1 (6+6+2+5+2+3+1+4+3+8), used as a proxy for Kernel 2's card-defined
  CDOL1. Response: '9F27' CID (4 B TLV), '9F36' ATC (5 B TLV) and '9F4B' SDAD
  — C-2 Table 5.10's three mandatory objects; optional IAD excluded.
- GPO (B): PDOL data = TTQ 4 + UN 4 + Amount 6 + Currency 2 = 16 bytes
  (C-3 Table C-1 plus '9F66'); response '82' AIP (4 B TLV), '94' AFL (one
  4-byte entry, 6 B TLV), '9F4B' SDAD. '9F69' Card Authentication Related
  Data travels in the last record (C-3 Fig. C-1) and is excluded (identical
  classical and PQ).
- GPO (C): PDOL data = Kernel Key Data (64 B, P-256 x‖y) + Kernel Qualifier
  (8 B); response AIP, AFL (one entry), '9F8103' Card Key Data (64 B).
These fields are identical in classical and PQ forms except where the PQ
form replaces the key data.

## Classical baselines

### D-K1 RSA (A, B)
NCA = 248, NI = 247 (Book 2 Table 43 maxima). NIC = 239: Book 2 D1.2.1
allows 240 for CDA without IAD, but with D-T3's B response (AIP 4 + AFL 6 +
'9F4B' TLV) 240 gives 257 bytes; 239 is the largest NIC for which both
the A GENERATE AC response (255 B) and the B GPO response (256 B) fit.
Exponents 3 (1 byte). Records: issuer certificate '90' alone (254-byte
record); ICC certificate '9F46' alone (254); one record with '8F' (3 B TLV),
'92' (35 B remainder, 37 B TLV), '9F32' (4), '9F48' (34 B remainder, 37 B
TLV), '9F47' (4) = 85 B → 87-byte record. Depth 1 drops the issuer record
and '8F', '92', '9F32' (remaining record 43 bytes).
Classical card and reader computation: not modelled.

### D-K2 ECC (C)
P-256 / EC-SDSA per Book E: issuer certificate 117 B, ICC certificate 145 B,
Kernel Key Data 64 B, Card Key Data 64 B. Records: '70' ['8F'][ '90' 117 ]
(124 B) and '70' ['9F46' 145 ] (152 B). Depth 1 drops the issuer record.

## Post-quantum message formats

### D-C1 Certificate format
Baseline (Book E style, appended signature; Book E §5):
- issuer certificate = 21 + |pk_S| + |sig_S|
- ICC certificate, A/B = 17 + 32 (ICCD hash) + |pk_S| + |sig_S|
- ICC certificate, C = 17 + 32 + |ek_K| + |sig_S|
Alternative D-C1b (Book 2 field layout, no message recovery possible with
lattice signatures, static data hashed into the signature): issuer
14 + |pk| + |sig|; ICC 20 + |pk| + |sig|. Difference: −7 and −29 bytes.
One signature scheme S for the whole chain (CA, issuer, and card in A/B).

### D-C2 Certificate transport
Book 3 §7.1 limits a record to 254 bytes; C-8 caps '90'/'9F46' at 248 bytes.
Baseline D-R1: each PQ certificate is split into consecutive records, each
'70' L [ T(2) L(2) fragment ], fragment ≤ 247 bytes (record = 254 bytes);
new 2-byte fragment tags. Depth 2 adds one record '70' 03 '8F' 01 xx
(5 bytes). Each record costs one READ RECORD exchange (C-APDU 5 bytes).
Alternative D-R2 (extended-length APDUs, ISO/IEC 7816-4; outside Book 1's
256-byte rule): one exchange per certificate, C-APDU 7 bytes, response
= T(2) L(3) certificate + SW, carried by L1 chaining.

### D-S1 Signature and large-response transport (card → reader)
Book 1 limits a response to 256 data bytes. Baseline: the response data
(template included) is returned in 256-byte pieces; the first in the
original exchange with SW '61xx', each further piece by a GET RESPONSE
C-APDU (5 bytes). Pieces = ceil(D/256). Alternative D-R2: one extended
response.

### D-S2 Large command data (reader → card)
Command data > 255 bytes (C: KEM ciphertext, ephemeral key) is sent by
ISO/IEC 7816-4 command chaining: ceil(D/255) C-APDUs of 4 + 1 + ≤255 bytes;
non-final ones answered by SW '9000' only. Alternative D-R2: one extended
C-APDU (4 + 3 + D bytes).

## Architecture C, post-quantum forms

C-8 sends the reader's ephemeral key in GPO but the card's certified key only
in READ RECORD (C-8 §3.3, Tables 5.1 and 5.11). A KEM where the reader encapsulates to the
card's static key must therefore wait until after the records.

### D-C3 C-min (the card decapsulates)
1. GPO without key data (PDOL: Kernel Qualifier 8 B); response AIP, AFL.
2. READ RECORD: certificates **in clear** (no session key exists yet).
3. New command ESTABLISH: reader sends ct = Encaps(ek_C) (command chaining);
   card decapsulates; SW '9000'.
4. GENERATE AC unchanged (EDA-MAC under the derived session key).
Change from C-8: one new command; certificates travel unencrypted, so the
card is identifiable to an eavesdropper — **C-8's privacy property is lost**.
Card: 1 decapsulation. Reader: signature verifications (2 at depth 2, 1 at
depth 1) + 1 encapsulation.

### D-C4 C-priv (privacy-preserving variant, after IDEMIA Fig. 4)
1. GPO: reader sends an ephemeral KEM key ek_T (command chaining); card
   encapsulates to it (ct1, K1) and returns ct1 (D-S1 pieces).
2. READ RECORD: certificates encrypted under K1 (AES-CTR, same length).
3. ESTABLISH: reader sends ct2 = Encaps(ek_C), encrypted under K1; card
   decapsulates; K = KDF(ss1‖ss2).
4. GENERATE AC unchanged.
Card: 1 encapsulation + 1 decapsulation. Reader: KEM keygen + decapsulation
+ verifications + encapsulation. New PQ object tags are 3 bytes (C-8 style).
Alternatives considered and not modelled: static-key encapsulation in GPO
(impossible: the reader lacks ek_C); caching ek_C (reintroduces tracking).

## Card computation

### D-W1 Computation and S(WTX)
A computing command's response starts T_c after the command frame (T_c =
cycles / f_card; D-P4's FDT_A,PICC is not added on top). Window
W = FWT_MAX(card) = 524 288/fc (L1 10.2.2, Table A.6). S(WTX) count
n = max(0, ⌈T_c / W⌉ − 1). Baseline: computation pauses during each S(WTX)
exchange, which costs a card frame of 4 bytes (37 etu, card tariff),
FDT_A,PCD (reader tariff) and a reader frame of 4 bytes (38 etu, reader
tariff): 16 380/fc per round trip. Alternative: computation continues during
the exchange (added latency 0; count unchanged). Both are reported.

### D-W2 Cycle statistic
Baseline: mean cycles as published. Sensitivities: pqm4/pqm3 observed MAX;
Pornin's stated "nine nines" figures (P26 p.34) quoted, not modelled.

### D-W3 Core classes and implementations
Cycle counts are taken only from measurements on the named core class:
- Cortex-M4 (no payment chip found uses it): pqm4 `clean` (central),
  `m4f`/`m4fspeed`, `m4fstack`; FN-DSA `ref` and `m4f`; P26 new code;
  HUANG (round-3 Dilithium/Kyber).
- Cortex-M3 class (SC300): pqm3 `clean` and `m3` (round-3 Kyber512/768/1024,
  Dilithium2/3); GKS21 (round-2 Dilithium2/3/4, run as their own parameter
  sets with their own sizes).
- Cortex-M0 class (SC000): M0P (Cortex-M0+, PQClean reference C).
No figure is scaled between core classes. Where a class has no measurement
for a scheme, the result is "no published measurement".
Round-3 cycle counts are used for the FIPS scheme with the same module
dimensions: Dilithium2 → ML-DSA-44, Dilithium3 → ML-DSA-65, Dilithium5 →
ML-DSA-87, KyberN → ML-KEM-N. Object sizes always use the FIPS values.
Sizes are identical for Dilithium2/ML-DSA-44 (pk 1312, sig 2420) and for
Kyber/ML-KEM; they differ for Dilithium3 (sig 3293) vs ML-DSA-65 (3309) and
Dilithium5 (sig 4595) vs ML-DSA-87 (4627) — FIPS 204 lengthens c-tilde.
(Source of the round-3 sizes: pqm3 `crypto_sign/dilithium2/m3/params.h`,
`CRYPTO_BYTES = SEEDBYTES + L*POLYZ_PACKEDBYTES + OMEGA + K` with SEEDBYTES
32; pqm4's ML-DSA `params.h` uses CTILDEBYTES 32/48/64 in that position.)
The mapping is labelled wherever used; cycle counts are close, not identical.

### D-W4 Clocks
Required card clocks are compared with brief clocks only where a brief states
one: ST31N600 60 MHz, ST31P450 55 MHz (SC000); Infineon
SLC36/37 80 MHz (SC300; brief also says "over 80 MHz"). NXP: none stated.
No clock is estimated.

## RAM

### D-M1 Card RAM required
Required = implementation stack/work RAM (as published) + buffers the
harness excludes that must be in RAM on a card + link buffer:
- signing: signature output buffer (|sig|) + message (32 B, pqm4's stack
  harness MLEN) ; secret key in NVM (not RAM).
- decapsulation: ciphertext (|ct|) + shared secret (32 B); dk in NVM.
- encapsulation (C-priv): received ek_T (|ek|) + ct1 (|ct|) + 32 B.
- link: one APDU buffer of 261 bytes (5 + 255 + 1).
Alternative D-M1b: secret key copied to RAM (+|sk|).
P26's RAM (20n + 992) and M0P's "Total RAM" are used as published and the
buffers above added only where the source excludes them (M0P's stack
column excludes them; its Total column includes caller-allocated keys,
ciphertexts, signatures — M0P Table IX text).

### D-M2 Card RAM available
Brief "Kbytes" = 1024 bytes (baseline); alternative 1000 bytes. Brief RAM is
total user RAM before the operating system and applets; "fits" is therefore
conditional, "exceeds" is safe.

## Reader processing

### D-R3 Reader computation
Reader cycles from pqm4 Cortex-M4 `m4f`/`m4fspeed` (verify, encaps, keygen,
decaps), labelled "Cortex-M4-class reader MCU". No reader clock is assumed:
the result is the reader clock needed to fit the reader tariff after the
reader's transmission and gaps.

## Reading the sources

### D-X1 Digits stored as glyph names
In two papers (P19, P26) the digits in some tables are stored as glyph names
in the PDF, so copying the text gives garbage. They were read with the pypdf
library instead. That step is not part of `run.py`; the numbers are typed into
`data/literature.json` with their page numbers.

## Findings of the paper

| | Finding | Paper |
|---|---|---|
| F1 | EMV has one bit rate, about 106 kbit/s, in both directions | §2 |
| F2 | A reader must answer every waiting-time extension, so L1 does not bound card computation | §2 |
| F3 | Every post-quantum object is larger than EMV's message and record containers | §2 |
| F4 | Kernel 8 style: the reader's transmission alone exceeds 100 ms in 27 of 30 configurations | §4.1 |
| F5 | The other three exceed it once the reader's frame delays count | §4.1 |
| F6 | ML-DSA-65/87 certificate chains exceed the reader's 100 ms in A and B | §4.2 |
| F7 | ML-DSA and FN-DSA-1024 signing designs exceed the card's 400 ms on transmission | §4.2 |
| F8 | No published FIPS 204 signer that runs on SC300/SC000 fits their RAM | §4.3 |
| F9 | The best Kernel 8-style design fails once the rest of the transaction and the polling waits count | §4.1 |
| F10 | FN-DSA-512 transmits in time, but no signer that fits the RAM is fast enough | §4.4 |
| F11 | Unprotected ML-KEM decapsulation fits the card; protected, it is unresolved on SC300 | §4.4 |
| F12 | The classical baselines fit easily in the same model | §3 |
| F13 | No published KEM construction offers Kernel 8's key blinding | §4.5 |
| F14 | The byte model reproduces IDEMIA's published post-quantum sizes | §3 |
| F15 | Caching issuer keys (non-standard depth 1) does not rescue Kernel 8-style designs | §4.1 |

## Corrections made during the analysis

Every value in the paper is the corrected one.

| | What changed | Effect |
|---|---|---|
| E1 | The rest of a Kernel 8 transaction counted one reader frame delay too many (none follows the last response) | R_min = 9.833 ms; the best margin is −10.184 ms with the polling waits |
| E2 | The same extra delay in the depth-1 results | Depth-1 margins move by +0.500 ms; the best is −0.596 ms |
| E3 | Architecture A's reader times had an unneeded delay after the last response | Every architecture-A reader time drops by 0.500 ms |
| E4 | Added Bos, Renes and Sprenkels (2022), round-3 Dilithium-2 signing in 5.0 KiB of stack | The RAM finding is an engineering gap, not an impossibility |
| E5 | Added the only measured figure for RAM free for cryptography (about 4.5 kB) | `analyses/ram_4500.py` |
| E6 | Added a protected ML-KEM figure on a Cortex-M3 | The card side of a KEM design is unresolved on SC300 and likely too slow on SC000 (`analyses/protected_mlkem.py`) |
| E7 | Added Dottax and Zeitoun (2026) to the privacy discussion | No value changes |

## Papers referred to by short keys

| Key | Paper |
|---|---|
| ALN25 | Alnahawi et al., Post-quantum cryptography in eMRTDs, SSR 2025 (ePrint 2025/812) |
| AZ22 | Azouaoui et al., Protecting Dilithium against leakage, TCHES 2023(4) |
| BDG25 | Bettale, Dottax and Grémy, Post-quantum secure channel protocols for eSIMs, SECRYPT 2025 |
| BRS22 | Bos, Renes and Sprenkels, Dilithium for memory constrained devices, AFRICACRYPT 2022 |
| DZ26 | Dottax and Zeitoun, Post-quantum authentication for embedded systems: PIV, ePrint 2026/1274 |
| GKS21 | Greconici, Kannwischer and Sprenkels, Compact Dilithium on Cortex-M3 and Cortex-M4, TCHES 2021(1) |
| HUANG | Huang et al., Revisiting Keccak and Dilithium implementations on ARMv7-M, TCHES 2024(2) |
| IDEMIA | Bettale, De Oliveira and Dottax, Post-quantum protocols for banking applications, NIST PQC conference 2022 |
| M0P | Chhetri, Dhakal and Gautam, ML-KEM and ML-DSA on the Cortex-M0+ (RP2040), arXiv 2603.19340 |
| P19 | Pornin, New efficient, constant-time implementations of Falcon, ePrint 2019/893 |
| P25 | Pornin, Falcon on ARM Cortex-M4: an update, ePrint 2025/123 |
| P26 | Pornin, A RAM-efficient implementation of Falcon, ePrint 2026/1915 |
| PQ-EAC | Fischlin et al., Post-quantum security for the extended access control protocol, SSR 2023 (ePrint 2023/352) |
