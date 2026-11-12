"""The command line: `absg gate`, `absg explain`, `absg limits`.

This file exists to be the thing a pipeline calls. It is argparse because the deployment target
is a CI step with nothing installed (ADR-004), and its exit codes are the interface: 0 clean, 1
breach, 2 could not answer, 3 usage. Every input is validated at this boundary so that a broken
project, coverage report or policy file is reported with the file and the reason, and never
analysed as if it were whole.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from absg import __version__
from absg.coverage import CoverageError, load_coverage
from absg.exit_codes import USAGE
from absg.limits import PolicyError, load_policy
from absg.project import ProjectError, load_project
from absg.report import explain_text, render_html, render_json, render_markdown, render_text
from absg.verdict import run_gate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="absg",
        description="Computes the record count at which every trigger in an SFDX project "
        "breaches a governor limit, and places it next to the largest record count any test "
        "exercised.",
    )
    parser.add_argument("--version", action="version", version=f"absg {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--project", default=".", help="SFDX project root (default: current directory)"
        )
        p.add_argument("--coverage", help="test-result-codecoverage.json from sf apex run test")
        p.add_argument(
            "--records", type=int, help="record count the verdict is taken at (default 200)"
        )
        p.add_argument("--context", choices=["sync", "async"], default="sync")
        p.add_argument("--policy", help="JSON policy file overriding limit values")

    gate = sub.add_parser("gate", help="report every trigger's breach size and exit 0/1/2")
    common(gate)
    fmt = gate.add_mutually_exclusive_group()
    fmt.add_argument("--json", action="store_true", help="print the full result as JSON")
    fmt.add_argument("--markdown", action="store_true", help="print a markdown job summary")
    fmt.add_argument("--html", metavar="FILE", help="also write an HTML report to FILE")

    explain = sub.add_parser("explain", help="show one trigger's sites and breach arithmetic")
    explain.add_argument("trigger")
    common(explain)

    limits = sub.add_parser("limits", help="print the limit policy with the reason for each value")
    limits.add_argument("--policy", help="JSON policy file overriding limit values")
    limits.add_argument("--context", choices=["sync", "async"], default="sync")
    limits.add_argument("--json", action="store_true")
    return parser


def _load(args: argparse.Namespace, err=sys.stderr):
    try:
        policy = load_policy(args.policy, args.context, args.records)
    except PolicyError as exc:
        print(f"absg: policy: {exc}", file=err)
        return None
    try:
        project = load_project(args.project)
    except ProjectError as exc:
        print(f"absg: project: {exc}", file=err)
        return None
    if project.load_errors:
        for error in project.load_errors:
            print(f"absg: project: {error}", file=err)
        return None
    coverage = None
    if args.coverage:
        try:
            coverage = load_coverage(args.coverage)
        except CoverageError as exc:
            print(f"absg: coverage: {exc}", file=err)
            return None
    return project, policy, coverage


def main(argv: list[str] | None = None, out=None, err=None) -> int:
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return USAGE if exc.code not in (0, None) else 0
    if args.command == "limits":
        try:
            policy = load_policy(args.policy, args.context, None)
        except PolicyError as exc:
            print(f"absg: policy: {exc}", file=err)
            return USAGE
        rows = policy.describe()
        if args.json:
            import json

            print(json.dumps(rows, indent=2), file=out)
        else:
            for row in rows:
                print(
                    f"{row['name']:<15} {row['value']:>7,} {row['unit']:<11} {row['reason']}",
                    file=out,
                )
        return 0
    loaded = _load(args, err)
    if loaded is None:
        return USAGE
    project, policy, coverage = loaded
    result = run_gate(project, policy, coverage)
    if args.command == "explain":
        try:
            verdict = result.by_name(args.trigger)
        except KeyError:
            print(
                f"absg: no trigger named {args.trigger!r}; "
                f"known: {', '.join(sorted(project.triggers))}",
                file=err,
            )
            return USAGE
        print(explain_text(verdict, result), end="", file=out)
        return 0
    if args.json:
        print(render_json(result), end="", file=out)
    elif args.markdown:
        print(render_markdown(result), end="", file=out)
    else:
        print(render_text(result), end="", file=out)
    if args.html:
        Path(args.html).parent.mkdir(parents=True, exist_ok=True)
        Path(args.html).write_text(render_html(result), encoding="utf-8")
    return result.exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
