"""Scan pqm4 implementation directories for instructions a Cortex-M3-class
(ARMv7-M without DSP/FPU) or Cortex-M0-class (ARMv6-M) core lacks.

Reads the pqm4 clone under sources/pqm4 (see the README) and writes
data/pqm4_isa_scan.json. Symbolic links stored as text stubs (a Windows clone
without symlink support) are followed.

Instruction classes (Arm Architecture Reference Manuals, v7-M and v6-M):
  dsp  - ARMv7E-M DSP extension (Cortex-M4/M7 only)
  fpu  - floating-point extension registers/instructions (M4F/M7 only)
  v7m  - ARMv7-M instructions absent from ARMv6-M (present on M3 and M4)
"""
import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
PQM4 = os.path.join(ROOT, "sources", "pqm4")

DSP = re.compile(
    r"\b(smla[bt][bt]|smlad|smladx|smlal[bt][bt]|smlald|smlaldx|smlsd|smlsdx|"
    r"smlsld|smuad|smuadx|smusd|smusdx|smul[bt][bt]|smulw[bt]|smlaw[bt]|smmul|"
    r"smmulr|smmla|smmlar|smmls|smmlsr|pkhbt|pkhtb|sadd16|ssub16|sasx|ssax|"
    r"uadd16|usub16|uasx|usax|uadd8|usub8|sadd8|ssub8|qadd16|qsub16|qadd8|"
    r"qsub8|qadd|qsub|qdadd|qdsub|sel|uxtb16|sxtb16|uxtab16|sxtab16|usad8|"
    r"usada8|ssat16|usat16|shadd16|shsub16|uhadd16|uhsub16|umaal)(\.w)?\b",
    re.I)
FPU = re.compile(r"\bv(mov|ldr|str|ldm|stm|add|sub|mul|mla|div|sqrt|push|pop|"
                 r"cvt|cmp|abs|neg|fma)(\.[a-z0-9.]+)?\b", re.I)
V7M = re.compile(r"\b(umull|smull|umlal|smlal|udiv|sdiv|ubfx|sbfx|bfi|bfc|"
                 r"clz|rbit|mls|ldrd|strd|tbb|tbh|cbz|cbnz)(\.w)?\b", re.I)
ASM_EXT = (".s", ".S", ".i")
C_EXT = (".c", ".h")

TARGETS = [
    ("crypto_kem", "ml-kem-512"), ("crypto_kem", "ml-kem-768"),
    ("crypto_kem", "ml-kem-1024"),
    ("crypto_sign", "ml-dsa-44"), ("crypto_sign", "ml-dsa-65"),
    ("crypto_sign", "ml-dsa-87"),
    ("crypto_sign", "fndsa_provisional-512"),
    ("crypto_sign", "fndsa_provisional-1024"),
]


def resolve(path, depth=0):
    """Follow a git symlink stored as a one-line text file."""
    if depth > 8 or not os.path.isfile(path):
        return path
    if os.path.getsize(path) < 300:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read().strip()
        if "\n" not in text and "/" in text and not text.startswith(("#", "/*", "//")):
            target = os.path.normpath(os.path.join(os.path.dirname(path), text))
            if os.path.exists(target):
                return resolve(target, depth + 1)
    return path


def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(re.split(r"(//|@|;)", line, maxsplit=1)[0]
                     for line in text.splitlines())


def scan_dir(d):
    counts = {"dsp": {}, "fpu": {}, "v7m": {}}
    asm_files, inline_asm_files = [], []
    for name in sorted(os.listdir(d)):
        p = resolve(os.path.join(d, name))
        if os.path.isdir(p):
            continue
        with open(p, encoding="utf-8", errors="replace") as f:
            text = f.read()
        if name.endswith(ASM_EXT):
            asm_files.append(name)
            body = strip_comments(text)
        elif name.endswith(C_EXT) and re.search(r"\b(__asm__|__asm|asm)\s*(volatile\s*)?\(", text):
            inline_asm_files.append(name)
            body = "\n".join(re.findall(r'"([^"\n]*)"', text))
        else:
            continue
        for cls, rx in (("dsp", DSP), ("fpu", FPU), ("v7m", V7M)):
            for m in rx.finditer(body):
                k = m.group(0).lower()
                counts[cls][k] = counts[cls].get(k, 0) + 1
    return {
        "asm_files": asm_files,
        "inline_asm_files": inline_asm_files,
        "dsp": dict(sorted(counts["dsp"].items())),
        "fpu": dict(sorted(counts["fpu"].items())),
        "v7m": dict(sorted(counts["v7m"].items())),
    }


def main():
    out = {}
    for kind, scheme in TARGETS:
        base = os.path.join(PQM4, kind, scheme)
        for variant in sorted(os.listdir(base)):
            d = os.path.join(base, variant)
            if os.path.isdir(d):
                out["%s/%s" % (scheme, variant)] = {"path": "pqm4/%s/%s/%s" % (kind, scheme, variant), **scan_dir(d)}
        clean = os.path.join(PQM4, "mupq", "pqclean", kind, scheme, "clean")
        if os.path.isdir(clean):
            out["%s/clean" % scheme] = {"path": "pqm4/mupq/pqclean/%s/%s/clean" % (kind, scheme), **scan_dir(clean)}
        ref = os.path.join(PQM4, "mupq", kind, scheme, "ref")
        if os.path.isdir(ref):
            out["%s/ref" % scheme] = {"path": "pqm4/mupq/%s/%s/ref" % (kind, scheme), **scan_dir(ref)}
    dest = os.path.join(ROOT, "data", "pqm4_isa_scan.json")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=1, sort_keys=True)
        f.write("\n")
    for k, v in out.items():
        print("%-32s asm=%2d inline=%d dsp=%-4d fpu=%-4d v7m=%d" % (
            k, len(v["asm_files"]), len(v["inline_asm_files"]),
            sum(v["dsp"].values()), sum(v["fpu"].values()), sum(v["v7m"].values())))


if __name__ == "__main__":
    sys.exit(main())
