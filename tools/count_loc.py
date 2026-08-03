"""Physical / blank / comment / code line counts for a list of Python files.

Local, dependency-free, deterministic. Used by Prompt 8F-R1 §9 to publish the
line reduction as a measured number rather than an estimate.

A line is BLANK when it is empty after stripping; a COMMENT line when it starts
with '#' or lies inside a module/class/function docstring or any other
string-literal statement that occupies whole lines; CODE otherwise. Docstrings
are found with the tokenizer, so a '#' inside a string is not miscounted.

    python tools/count_loc.py <file-or-glob> [...] [--csv out.csv] [--label L]
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import tokenize
from pathlib import Path


def classify_lines(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    physical = len(lines)
    blank = sum(1 for line in lines if not line.strip())

    comment_lines: set[int] = set()
    readline = io.StringIO(text).readline
    previous_end = (0, 0)
    for token in tokenize.generate_tokens(readline):
        if token.type == tokenize.COMMENT:
            comment_lines.update(range(token.start[0], token.end[0] + 1))
        elif token.type == tokenize.STRING:
            # A string that starts its own logical line is a docstring or a
            # free-standing string statement; a string used as a value is not.
            if token.start[0] > previous_end[0]:
                comment_lines.update(range(token.start[0], token.end[0] + 1))
        if token.type not in (tokenize.NL, tokenize.NEWLINE,
                              tokenize.INDENT, tokenize.DEDENT):
            previous_end = token.end

    comment = sum(1 for n in comment_lines if lines[n - 1].strip())
    return {
        "path": str(path),
        "physical_lines": physical,
        "blank_lines": blank,
        "comment_or_docstring_lines": comment,
        "code_lines": physical - blank - comment,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python tools/count_loc.py")
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--csv", default="")
    parser.add_argument("--label", default="")
    args = parser.parse_args(argv)

    rows = []
    for pattern in args.paths:
        for path in sorted(Path().glob(pattern)) or [Path(pattern)]:
            if path.is_file():
                rows.append(classify_lines(path))

    total = {"path": "TOTAL", "physical_lines": 0, "blank_lines": 0,
             "comment_or_docstring_lines": 0, "code_lines": 0}
    for row in rows:
        for name in total:
            if name != "path":
                total[name] += row[name]
    rows.append(total)

    if args.label:
        for row in rows:
            row["label"] = args.label

    fields = ["path", "physical_lines", "blank_lines",
              "comment_or_docstring_lines", "code_lines"]
    if args.label:
        fields.insert(0, "label")
    writer = csv.DictWriter(
        open(args.csv, "w", encoding="utf-8", newline="") if args.csv
        else sys.stdout, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
