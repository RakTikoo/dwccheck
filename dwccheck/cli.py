"""Command-line interface for dwccheck.

Subcommands:
  dwccheck check FILE [--format text|json|csv]
      Pre-flight check a Darwin Core occurrence file (CSV or TSV)
      before upload to GBIF. Findings are printed with GBIF's own
      flag names (see `dwccheck flags`). Exit code 0 means no errors
      (warnings may still be present); 1 means at least one error was
      found; 2 means the file could not be checked at all.
  dwccheck flags
      List every flag this tool can emit, with GBIF's definition.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys

from . import core
from .core import DwcError


def build_parser():
    parser = argparse.ArgumentParser(
        prog="dwccheck",
        description="Pre-flight check a Darwin Core occurrence file "
                    "(CSV/TSV) locally, before upload to GBIF. Reports "
                    "the subset of GBIF's occurrence-issue flags that "
                    "can be decided from the file alone. Everything "
                    "runs offline; your file never leaves your machine.")
    sub = parser.add_subparsers(dest="command")
    chk = sub.add_parser(
        "check", help="check one occurrence file (CSV or TSV)")
    chk.add_argument("file", help="the occurrence file to check")
    chk.add_argument("--format", default="text",
                     choices=("text", "json", "csv"),
                     help="report format (default: text)")
    sub.add_parser(
        "flags", help="list the flags dwccheck can emit, with "
                      "GBIF's definitions")
    return parser


def _format_text(result):
    findings = result["findings"]
    summary = result["summary"]
    lines = []
    lines.append(f"file: {result['file']}")
    lines.append(f"rows checked: {result['rows']} data rows, "
                 f"{len(result['columns'])} columns")
    if findings:
        lines.append("")
        for f in findings:
            where = f"row {f.row}" if f.row else "file"
            term = f" [{f.term}]" if f.term else ""
            lines.append(f"{where}: {f.flag}{term} — {f.message}")
        lines.append("")
    lines.append(f"summary: {summary['errors']} error(s), "
                 f"{summary['warnings']} warning(s)")
    lines.append("result: FAIL — fix the errors before uploading to GBIF."
                 if summary["errors"]
                 else "result: PASS — no errors found."
                 if not findings else
                 "result: PASS — no errors (warnings above).")
    return "\n".join(lines)


def _format_json(result):
    payload = {
        "file": result["file"],
        "rows": result["rows"],
        "columns": result["columns"],
        "findings": [f.as_dict() for f in result["findings"]],
        "summary": result["summary"],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _format_csv(result):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["row", "flag", "severity", "term", "value", "message"])
    for f in result["findings"]:
        writer.writerow([f.row, f.flag, f.severity, f.term, f.value,
                         f.message])
    return buf.getvalue().rstrip("\n")


def cmd_check(args):
    result = core.check_file(args.file)
    if args.format == "json":
        print(_format_json(result))
    elif args.format == "csv":
        print(_format_csv(result))
    else:
        print(_format_text(result))
    return 1 if result["summary"]["errors"] else 0


def cmd_flags(_args):
    for entry in core.flag_definitions():
        print(f"{entry['flag']} ({entry['severity']}, {entry['origin']})")
        print(f"    {entry['definition']}")
    return 0


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.command is None:
        parser.print_help(sys.stderr)
        return 2
    try:
        if args.command == "check":
            return cmd_check(args)
        if args.command == "flags":
            return cmd_flags(args)
    except DwcError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # user errors must never show a traceback
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
