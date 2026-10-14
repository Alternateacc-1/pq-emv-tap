"""Transcribe pqm4 and pqm3 benchmark tables into data/*.json.

Reads the pqm4 and pqm3 clones in sources/ (see the README) and writes
data/bench_pqm4.json and data/bench_pqm3.json. Only the speed (cycles) and
memory (stack bytes) sections are read. run.py re-runs this transcription
when the clones are present and fails if the committed JSON differs.
"""
import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")

FILES = {
    "pqm4": os.path.join(ROOT, "sources", "pqm4", "benchmarks.md"),
    "pqm3": os.path.join(ROOT, "sources", "pqm3", "benchmarks-nucleo-f207zg.md"),
}

STAT = re.compile(r"AVG:\s*([\d,]+)\s*<br\s*/>\s*MIN:\s*([\d,]+)\s*<br\s*/>\s*MAX:\s*([\d,]+)")


def num(s):
    return int(s.replace(",", "").strip())


def parse(path):
    speed, stack = {}, {}
    section = None
    kind = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("# "):
                section = line[2:].strip()
                continue
            if line.startswith("## "):
                kind = "kem" if "Key Encapsulation" in line else "sign"
                continue
            if not line.startswith("|") or line.startswith("| scheme") or line.startswith("| Scheme") or line.startswith("| ---"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            name = re.sub(r"\s*\(\d+ executions\)", "", cells[0]).strip()
            m = re.search(r"\((\d+) executions\)", cells[0])
            impl = cells[1]
            key = "%s/%s" % (name, impl)
            ops = ("keygen", "encaps", "decaps") if kind == "kem" else ("keygen", "sign", "verify")
            if section == "Speed Evaluation":
                entry = {"kind": kind, "executions": int(m.group(1)) if m else None}
                for op, cell in zip(ops, cells[2:5]):
                    s = STAT.search(cell)
                    entry[op] = {"avg": num(s.group(1)), "min": num(s.group(2)), "max": num(s.group(3))}
                speed[key] = entry
            elif section == "Memory Evaluation":
                stack[key] = {"kind": kind, **{op: num(c) for op, c in zip(ops, cells[2:5])}}
    return {"speed_cycles": speed, "stack_bytes": stack}


def main():
    for name, path in FILES.items():
        data = parse(path)
        dest = os.path.join(ROOT, "data", "bench_%s.json" % name)
        with open(dest, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=1, sort_keys=True)
            f.write("\n")
        print(name, len(data["speed_cycles"]), "speed rows,", len(data["stack_bytes"]), "stack rows")


if __name__ == "__main__":
    sys.exit(main())
