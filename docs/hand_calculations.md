# Hand calculations

T01–T12 were written down before the code that computes them.
Each value below was worked out by hand from the specifications and the
choices in `modelling_choices.md`.
`run.py` must reproduce every one exactly (as a fraction) or fail.
Baseline: fc = 13 560 000 Hz, FSD = FSC = 256, D-T1 gap assignment.

## T01 Elementary time unit
etu = 128/fc = 128/13 560 000 s = **2/211 875 s** (≈ 9.43953 µs).

## T02 Card per-byte cost
One byte in a frame = 9 etu = 1152/fc s = **24/282 500 s** = 6/70 625 s
(≈ 84.956 µs). Check: 1152/13 560 000 = 24/282 500 (÷ 48).

## T03 Card maximum frame waiting time
FWT_MAX(card) = 4096 × 2^7 / fc = 524 288/13 560 000 = **8192/211 875 s**
(≈ 38.6643 ms). (524 288 = 2^19; 13 560 000 = 2^6 × 211 875.)

## T04 ΔFWT
49 152/13 560 000 = **768/211 875 s** (≈ 3.6248 ms).

## T05 One S(WTX) round trip
Card S(WTX) request, 4 bytes: 9×4 + 1 = 37 etu. Reader S(WTX) response,
4 bytes: 9×4 + 2 = 38 etu. Reader turnaround FDT_A,PCD = 6780/fc.
Total = 75 × 128/fc + 6780/fc = 16 380/fc = **273/226 000 s** (≈ 1.207965 ms).
Split: card 37 × 128/fc = 4736/fc; reader 38 × 128 + 6780 = 11 644/fc.

## T06 Frame costs
- 5-byte C-APDU (READ RECORD / GET RESPONSE): block 8 bytes → reader frame
  9×8 + 2 = **74 etu**.
- R-APDU of 256 bytes (254-byte record + SW): blocks INF 253 + INF 3 →
  card 9×256 + 1 = 2305 etu; reader R(ACK) 3 bytes → 29 etu; card block
  6 bytes → 55 etu. Card frames **2360 etu**, reader frames 74 + 29 = **103 etu**.

## T07 Classical A (Kernel 2 CDA, RSA, depth 2): exchanges and tariffs
Exchanges (D-K1, D-T3):
1. READ RECORD issuer ('90' 248 B; record 254 B): card 2360 etu, reader
   103 etu, 2 FDT_PICC, 2 FDT_PCD.
2. READ RECORD ICC ('9F46' 247 B; '70' 81 FB …; record 254 B): same as 1.
3. READ RECORD misc (87-byte record): R-APDU 89 → block 92 → card
   9×92 + 1 = 829 etu; reader 74 etu; 1 FDT_PICC, 1 FDT_PCD.
4. GENERATE AC: C-APDU 4 + 1 + 40 + 1 = 46 → block 49 → reader 443 etu.
   Response data: '9F27' (4) + '9F36' (5) + '9F4B' 81 EF + 239 (243) = 252
   → '77' 81 FC → 255; R-APDU 257 → blocks INF 253 (2305 etu) + R(ACK)
   (29 etu) + INF 4 → 7 bytes (64 etu). Card 2369 etu, reader 472 etu;
   2 FDT_PICC (classical computation not modelled), 2 FDT_PCD.

Totals: card frames 2360 + 2360 + 829 + 2369 = **7918 etu**; reader frames
103 + 103 + 74 + 472 = **752 etu**; FDT_PICC ×7; FDT_PCD ×7.
- Card tariff = (7918 × 128 + 7 × 1172)/fc = (1 013 504 + 8 204)/fc
  = **1 021 708/13 560 000 s** (≈ 75.3472 ms).
- Reader tariff = (752 × 128 + 7 × 6780)/fc = (96 256 + 47 460)/fc
  = **143 716/13 560 000 s** (≈ 10.5985 ms).
- APDU-level bytes: card R-APDUs 256 + 256 + 89 + 257 = **858**; reader
  C-APDUs 5 + 5 + 5 + 46 = **61**.

## T08 PQ A, ML-DSA-44, depth 2 (D-C1, D-R1, D-S1): bytes
- Issuer certificate 21 + 1312 + 2420 = **3753**: 15 × 247 = 3705, remainder
  48 → **16 records** (15 × 254 B; last: '70' 33 [T2 L1 48] = 53 B).
- ICC certificate 17 + 32 + 1312 + 2420 = **3781**: remainder 76 →
  **16 records** (last: inner 2 + 1 + 76 = 79 → 81 B).
- '8F' record: 5 B.
- READ RECORD exchanges: 33; reader bytes 33 × 5 = 165; card R-APDU bytes
  30 × 256 + 55 + 83 + 7 = **7825**.
- GENERATE AC response data: '9F4B' 82 09 74 + 2420 = 2425; + 4 + 5 = 2434
  inner; '77' 82 09 82 → **2438**. Pieces ⌈2438/256⌉ = **10** (9 × 256 + 134).
  Card R-APDU bytes 9 × 258 + 136 = **2458**; reader 46 + 9 × 5 = **91**.
- Totals: card **10 283**, reader **256** APDU-level bytes.

## T09 S(WTX) count, ML-DSA-44 pqm4 `clean` mean sign at 24 MHz
T_c = 7 925 955 / 24 000 000 s. T_c / W = 7 925 955 × 211 875 / (24 000 000
× 8192) = 1 679 311 715 625 / 196 608 000 000 ≈ 8.5414 → ⌈·⌉ = 9 →
**n = 8**. Added time (D-W1 baseline) = 8 × 16 380/fc = **131 040/13 560 000
s** (≈ 9.6637 ms).

## T10 IDEMIA consistency
Keys + signatures + card KEM secret key, Kyber512/ML-KEM-512 (ek 800,
dk 1632), two signatures and one signature public key per chain:
- Falcon-512: 897 + 666 + 800 + 666 + 1632 = **4661** = IDEMIA Table 2.
- Falcon-1024: 1793 + 1280 + 800 + 1280 + 1632 = **6785** = IDEMIA Table 2.
- Dilithium2: 1312 + 2420 + 800 + 2420 + 1632 = **8584** = IDEMIA Table 2.
- Dilithium3 (round-3 sig 3293): 1952 + 3293 + 800 + 3293 + 1632 = **10 970**
  = IDEMIA Table 2. (With ML-DSA-65's 3309 it would be 11 002.)
- Our D-C1 format adds 21 + 17 + 32 = **70** bytes of headers to each.

## T11 RAM (D-M1)
- P26 FN-DSA-512: 20 × 512 + 992 = 11 232; + sig 666 + msg 32 + APDU 261 =
  **12 191** bytes. ≤ 12 288 (12 KB, 1024-byte KB) → fits; > 12 000
  (1000-byte KB) → exceeds; > 10 240 → exceeds 10 KB parts.
- pqm4 ML-KEM-512 `m4fstack` decapsulation: 2332 + 768 + 32 + 261 = **3393**.
- pqm4 ML-DSA-44 `clean` sign: 51 976 + 2420 + 32 + 261 = **54 689** > 16 384.

## T12 Structural
- Closed-form totals equal the frame-by-frame simulation for every
  configuration (exact Fraction equality).
- Required card clock f* satisfies: card time at f* ≤ budget and card time
  at f* − 1 Hz > budget (integer-Hz search) — or "no clock" when
  transmission and gaps alone exceed the budget.

## T13 Mandatory Kernel 8 remainder R_min

This one was added after `analyses/kernel8_rmin.py` was written. It was
worked out by hand from the quoted clauses, independently of the script, so it
is an independent check rather than a prior specification like T01–T12.
`tests/test_rmin_by_hand.py` (run by `run.py`) checks every value below exactly.

### Quoted clauses (L1 v4.0; identical wording and values in v3.2)

> **9.2 (informative text, p.207):** "During the polling, the PCD sends poll commands until a response is received. In one polling cycle, all supported technology poll commands are sent. The PCD completes at least one polling cycle after a technology is detected. The PCD always polls for Type A and Type B, but may also poll for other technologies."

> **9.2.1.1:** "The PCD shall poll for Type A and Type B. The PCD may poll for other technologies."

> **9.2.1.3 (p.209), in full:** "The PCD shall check the value of TYPE_A (symbol 2). If TYPE_A is different from zero, then the PCD shall conclude the polling procedure and continue with the collision detection procedure. If TYPE_A is equal to zero, then: • The PCD shall wait a time tP with unmodulated carrier (symbol 3) before sending a WUPA command (symbol 4). • If the PCD receives any response (correct or not) to the WUPA command, then: o The PCD shall set TYPE_A equal to 1 (symbol 6) and shall send a HLTA command (symbol 7) to put the PICC(s) back in the IDLE state. o The PCD shall continue with 9.2.1.4."

> **9.2.1.4 (p.210), in full:** "The PCD shall check the value of TYPE_B (symbol 8). If TYPE_B is different from zero, then the PCD shall conclude the polling procedure and continue with the collision detection procedure. If TYPE_B is equal to zero, then: • The PCD shall wait a time tP with unmodulated carrier (symbol 9) before sending a WUPB command (symbol 10). • If the PCD receives any response (correct or not) to the WUPB command, then: o The PCD shall set TYPE_B equal to 1 (symbol 12). o The PCD shall continue with 9.2.1.5."

> **9.2.1.5 (p.210):** "If the PCD supports only Type A and Type B, then the PCD shall continue with 9.2.1.3. Otherwise, the PCD shall continue with 9.2.1.6."

> **9.2.1.7 (p.212):** "If the PCD supports other technologies, then the PCD shall suspend the Operating Field (as defined in section 3.2.10) before continuing with 9.2.1.3 (symbol 20)."

> **9.3.2.1 (p.214), in full:** "The PCD shall wait a time tP with unmodulated carrier (symbol 0) before sending a WUPA command (symbol 1). If the PCD detects a transmission error in the response to the WUPA command, then the PCD shall report a collision to the terminal, reset the Operating Field (as defined in section 3.2.6), and return to the polling procedure no later than tRESETDELAY measured from the start of the response (i.e. the start of SoF as defined in section 4.8). Otherwise, the PCD shall continue with 9.3.2.2."

> **t_P — Annex A.5, Table A.7 "PCD Processing" (p.256, read with `pdftotext -raw` and pypdf):** row "tP 5.1 10 5 ms" under the columns "PCD Value Min Max | PICC Value | Units". Preamble: "Unless otherwise specified, the value for the PCD is used when the parameter is referenced in a PCD requirement." 9.2.1.4 and 9.3.2.1 are PCD requirements, so **t_P ≥ 5.1 ms (a minimum; maximum 10 ms)**. The PICC value, 5 ms, bounds the card's power-on (3.2.8.1: "it shall enter the IDLE state no later than tP"). v3.2 Table A.7: same values.

> **Frame formats:** 4.7.1 short frame: "Start of Frame (SoF) • 7 data bits transmitted LSB first • End of Frame (EoF) No parity is added."; 5.3.1 "The WUPA and REQA commands are transmitted within a short frame."; 5.6.1 "The HLTA command consists of two bytes and is transmitted with CRC_A within a standard frame." ('50' '00'); 5.4.1 "The ANTICOLLISION command is transmitted within a standard frame without CRC_A." (SEL '20'); 5.5.1 "The SELECT command is transmitted with CRC_A within a standard frame." (SEL '70' UID CLn, bytes 3–7); 5.7.1 "The RATS command is transmitted with CRC_A within a standard frame." ('E0' PARAM); Table 6.2 WUPB "'05' AFI PARAM". Type B timing (Table A.6, PCD Min): tPCD,S,1 1280/fc, tPCD,S,2 248/fc, tPCD,E 1280/fc, EGTPCD 0; 4.6.2.1: "The EoS shall come immediately after the last bit of the last data character (i.e. EGTPCD does not apply)." APDU minima (PPSE name, Le, 5-byte ADF Name, empty CDOL1 data) as in STAGE4_CHECKS §5.2/§5.7.

### Can a reader skip the Type B poll after detecting a Type A card?

**No reading found.** After a response to the polling WUPA, 9.2.1.3 obliges
the PCD to send HLTA and "continue with 9.2.1.4"; there TYPE_B is still 0 (a
Type A card does not answer WUPB), so the PCD "shall wait a time tP … before
sending a WUPB command". Polling is concluded only when 9.2.1.5 returns to
9.2.1.3 and finds TYPE_A ≠ 0. The informative text agrees: "The PCD completes
at least one polling cycle after a technology is detected." Readings checked:

1. *Card enters the field just after a WUPB.* Its first response is then to the next WUPA (9.2.1.3 precedes 9.2.1.4 in every cycle), and a WUPB with its t_P still follows. No skip.
2. *PCD supports other technologies.* 9.2.1.5 → 9.2.1.6 (proprietary polls) → 9.2.1.7 (field suspend): more steps, not fewer.
3. *Poll for Type A only.* Excluded by 9.2.1.1 "shall poll for Type A and Type B".
4. *Shorter t_P.* Table A.7 gives 5.1 ms as the PCD minimum; the PICC value (5 ms) applies to PICC requirements only.
5. *t_P overlapping a frame or gap.* t_P is "with unmodulated carrier" before the next command; it cannot overlap HLTA or WUPB (modulated). The reader's wait for a possible ATQB after WUPB is not counted (it may coincide with the second t_P), which keeps R a lower bound.
6. *Book A's clock starting later.* §10.1 starts at "the first ISO 14443-3 command from the reader to which the card responds": the polling WUPA, whose response sets TYPE_A.

The headline margin is therefore **−10.184 ms**. The +0.016 ms figure would
hold only if both t_P waits were excluded from the reader tariff; no reading
of L1 v4.0 or v3.2 allows that.

### Hand derivation (fc = 13 560 000 Hz; 1 etu = 128/fc; Type A reader frame of n bytes = 9n + 2 etu; short frame 1 + 7 + 1 = 9 etu)

| # | Exchange | Reader frame | etu | 1/fc | seconds (exact) | FDT_A,PCD gaps |
|---|---|---|---|---|---|---|
| 1 | HLTA | '50' '00' + CRC_A = 4 B | 9·4 + 2 = 38 | 4 864 | 4864/13 560 000 | 1 (after the first ATQA, before HLTA; 4.8.2.1) |
| 2 | t_P (9.2.1.4) | — | — | — | 51/10 000 | 0 |
| 3 | WUPB | SoS 1280 + 248; 5 characters × 10 etu = 6 400; EGT 0; EoS 1280 | — | 9 208 | 9208/13 560 000 | 0 (no response) |
| 4 | t_P (9.3.2.1) | — | — | — | 51/10 000 | 0 |
| 5 | WUPA | short frame | 9 | 1 152 | 1152/13 560 000 | 1 (after ATQA) |
| 6 | ANTICOLLISION CL1 | '93' '20', no CRC = 2 B | 20 | 2 560 | 2560/13 560 000 | 1 (after UID CL1) |
| 7 | SELECT CL1 | '93' '70' + UID0–3 + BCC + CRC_A = 9 B | 83 | 10 624 | 10624/13 560 000 | 1 (after SAK) |
| 8 | RATS | 'E0' PARAM + CRC_A = 4 B | 38 | 4 864 | 4864/13 560 000 | 1 (after ATS; SFGI 0) |
| 9 | SELECT (PPSE) | PCB + 00 A4 04 00 0E + '2PAY.SYS.DDF01' (14) + Le + CRC = 23 B | 209 | 26 752 | 26752/13 560 000 | 1 (after response) |
| 10 | SELECT (AID) | PCB + 00 A4 04 00 05 + AID (5) + Le + CRC = 14 B | 128 | 16 384 | 16384/13 560 000 | 1 (after response) |
| 11 | GENERATE AC | PCB + CLA INS P1 P2 Le (CDOL1 data 0 B) + CRC = 8 B | 74 | 9 472 | 9472/13 560 000 | 0 (last command) |

- Frames: 38 + 9 + 20 + 83 + 38 + 209 + 128 + 74 = **599 etu** = 76 672/fc; + WUPB 9 208/fc = **85 880/fc = 19/3000 s** (6.3333… ms).
- Gaps: 7 × 6 780/fc = **47 460/fc = 7/2000 s** (3.5 ms).
- **R_min = 133 340/fc = 59/6000 s** (9.8333… ms).
- With t_P: 59/6000 + 2 × 51/10 000 = 295/30 000 + 306/30 000 = **601/30 000 s** (20.0333… ms).

C-min, FN-DSA-512 + ML-KEM-512, depth 2, FSD = FSC = 512 (F9). Modelled
reader frames 8 491 etu + 20 FDT_A,PCD gaps = (1 086 848 + 135 600)/fc =
1 222 448/fc = **76 403/847 500 s** (90.151 ms; from the model, T12).

- Margin without t_P: 1/10 − 1 222 448/fc − 133 340/fc = (1 356 000 − 1 222 448 − 133 340)/fc = **212/13 560 000 = 53/3 390 000 s** (+0.015634 ms). Reader clock for 1 184 779 Cortex-M4 cycles (two FN-DSA-512 verifications, one ML-KEM-512 encapsulation): 1 184 779 × 3 390 000/53 = 75 781 147 358.49… Hz → **⌈·⌉ = 75 781 147 359 Hz** (75 781.147 MHz).
- Margin with t_P: 212/fc − 51/5 000 = (212 − 138 312)/fc = **−138 100/13 560 000 = −1 381/135 600 s** (−10.1844 ms). No clock.
