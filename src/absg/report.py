"""Rendering the gate result: a text table for a terminal, JSON for a machine, markdown for a
CI job summary, HTML for the screenshots in the README.

This file exists so the numbers are computed once (verdict.py) and only formatted here. Every
format leads with the same table: coverage, breach size, tested size, verdict. The HTML carries
a verdict badge whose computed style the screenshot tool reads back, because a badge that
renders invisible is the one failure none of the tests can see.
"""

from __future__ import annotations

import html
import json

from absg.exit_codes import MEANING
from absg.verdict import GateResult, TriggerVerdict

LIMIT_LABELS = {
    "soql_queries": "SOQL queries",
    "sosl_queries": "SOSL queries",
    "dml_statements": "DML statements",
    "dml_rows": "DML rows",
}

STATUS_LABELS = {
    "breach": "BREACH",
    "latent": "LATENT",
    "clean": "CLEAN",
    "undecidable": "UNDECIDABLE",
}


def _fmt(value: int | float | None, suffix: str = "") -> str:
    if value is None:
        return "?"
    if isinstance(value, float):
        return f"{value:g}{suffix}"
    return f"{value:,}{suffix}"


def _rows(result: GateResult) -> list[list[str]]:
    rows = []
    for t in result.triggers:
        breach = t.smallest_breach()
        rows.append(
            [
                t.name,
                t.sobject,
                _fmt(t.coverage_pct, "%") if result.coverage_loaded else "n/a",
                _fmt(t.tested.largest) if t.tested.largest is not None else "?",
                _fmt(breach) if breach is not None else f"none within {result.policy.horizon:,}",
                STATUS_LABELS[t.status],
            ]
        )
    return rows


HEADERS = ["Trigger", "Object", "Coverage", "Tested at", "Breaches at", "Verdict"]


def render_text(result: GateResult) -> str:
    rows = _rows(result)
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(HEADERS)]
    lines = [
        f"absg gate: {len(result.triggers)} triggers, verdict at {result.policy.records:,} records "
        f"({result.policy.context}), horizon {result.policy.horizon:,}"
    ]
    lines.append("  ".join(h.ljust(w) for h, w in zip(HEADERS, widths, strict=True)))
    lines.append("  ".join("-" * w for w in widths))
    for r in rows:
        lines.append("  ".join(c.ljust(w) for c, w in zip(r, widths, strict=True)))
    lines.append("")
    for t in result.triggers:
        for f in t.findings:
            via = " via chain" if f.via_chain else ""
            tested = "?" if f.tested_largest is None else f"{f.tested_largest:,}"
            lines.append(
                f"  {t.name}: {LIMIT_LABELS[f.limit]} {f.cost_formula} per invocation, limit "
                f"{f.limit_value:,}, breaches at {f.breach_at:,} records{via}; tested at {tested}"
            )
        for r in t.refusals:
            lines.append(
                f"  {t.name}: undecidable, {r['reason']}: {r['construct']} "
                f"({r['path']}:{r['line']})"
            )
    for w in result.warnings:
        lines.append(f"  warning: {w}")
    counts = result.counts()
    lines.append("")
    lines.append(
        f"breach {counts['breach']}, latent {counts['latent']}, clean {counts['clean']}, "
        f"undecidable {counts['undecidable']}; exit {result.exit_code} "
        f"({MEANING[result.exit_code]})"
    )
    return "\n".join(lines) + "\n"


def render_json(result: GateResult) -> str:
    return json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"


def render_markdown(result: GateResult) -> str:
    rows = _rows(result)
    lines = [
        f"## absg gate: verdict at {result.policy.records:,} records ({result.policy.context})",
        "",
        "| " + " | ".join(HEADERS) + " |",
        "| " + " | ".join("---" for _ in HEADERS) + " |",
    ]
    lines.extend("| " + " | ".join(r) + " |" for r in rows)
    lines.append("")
    for t in result.triggers:
        for f in t.findings:
            via = " (via chain)" if f.via_chain else ""
            lines.append(
                f"- `{t.name}`: {LIMIT_LABELS[f.limit]} `{f.cost_formula}` per invocation, "
                f"breaches at {f.breach_at:,} records{via}, tested at "
                f"{'?' if f.tested_largest is None else f'{f.tested_largest:,}'}"
            )
        for r in t.refusals:
            lines.append(f"- `{t.name}`: undecidable, {r['reason']}: `{r['construct']}`")
    counts = result.counts()
    lines.append("")
    lines.append(
        f"Exit {result.exit_code}: {MEANING[result.exit_code]}. Breach {counts['breach']}, "
        f"latent {counts['latent']}, clean {counts['clean']}, undecidable {counts['undecidable']}."
    )
    return "\n".join(lines) + "\n"


def explain_text(verdict: TriggerVerdict, result: GateResult) -> str:
    lines = [
        f"{verdict.name} on {verdict.sobject} ({', '.join(verdict.events)}), {verdict.path}",
        f"verdict: {STATUS_LABELS[verdict.status]} at {result.policy.records:,} records",
        "",
        "sites (multiplier is the number of times the construct runs per invocation of r records):",
    ]
    for s in verdict.sites:
        mult = "x" + s["multiplier"] if s["multiplier"] is not None else "-"
        lines.append(f"  {s['path']}:{s['line']}  {s['kind']:<8} {mult:<10} {s['detail']}")
    lines.append("")
    lines.append("cost per invocation:")
    for limit, formula in verdict.costs.items():
        lines.append(f"  {LIMIT_LABELS[limit]:<15} {formula}")
    lines.append("")
    if verdict.findings:
        lines.append(
            f"breach arithmetic (chunks of {result.policy.chunk_size} share one transaction):"
        )
        for f in verdict.findings:
            lines.append(
                f"  {LIMIT_LABELS[f.limit]}: {f.cost_formula} per invocation > {f.limit_value:,} "
                f"at {f.breach_at:,} records{' via chain' if f.via_chain else ''}"
            )
    else:
        lines.append(f"no limit breached within {result.policy.horizon:,} records")
    tested = verdict.tested.largest
    lines.append("")
    lines.append(
        "tests: largest record count exercised "
        + ("unknown" if tested is None else f"{tested:,}")
        + (f" ({verdict.tested.unknown} exercise(s) unresolved)" if verdict.tested.unknown else "")
    )
    for e in verdict.tested.exercises:
        lines.append(
            f"  {e.test_class}.{e.test_method}:{e.line} {e.operation} {e.sobject} "
            f"{'?' if e.records is None else e.records} ({e.note})"
        )
    if verdict.refusals:
        lines.append("")
        lines.append("refusals:")
        for r in verdict.refusals:
            lines.append(f"  {r['reason']}: {r['construct']} ({r['path']}:{r['line']})")
    if verdict.guards:
        lines.append("")
        lines.append("static guards seen: " + ", ".join(verdict.guards))
    return "\n".join(lines) + "\n"


CSS = """
:root { --ink: #1b1f24; --muted: #57606a; --line: #d0d7de; --bg: #ffffff; --panel: #f6f8fa;
  --breach: #b42318; --breach-bg: #fde8e6; --latent: #8a5a00; --latent-bg: #fff4d6;
  --clean: #1a7f37; --clean-bg: #e3f6e8; --undec: #5b4bc4; --undec-bg: #ece9fb; }
body { font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  color: var(--ink);
  background: var(--bg); margin: 0; padding: 32px 40px; max-width: 1100px; }
h1 { font-size: 24px; margin: 0 0 6px; }
h2 { font-size: 18px; margin: 32px 0 10px; padding-top: 10px; border-top: 1px solid var(--line); }
p.sub { color: var(--muted); margin: 0 0 16px; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--line);
  vertical-align: top; }
th { background: var(--panel); font-weight: 600; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }
.badge { display: inline-block; padding: 2px 9px; border-radius: 12px; font-size: 12px;
  font-weight: 700;
  letter-spacing: .02em; }
.badge.breach { color: var(--breach); background: var(--breach-bg); }
.badge.latent { color: var(--latent); background: var(--latent-bg); }
.badge.clean { color: var(--clean); background: var(--clean-bg); }
.badge.undecidable { color: var(--undec); background: var(--undec-bg); }
.verdict { font-size: 15px; margin: 12px 0 0; }
.verdict .badge { font-size: 14px; padding: 4px 12px; }
ul.findings { padding-left: 18px; }
ul.findings li { margin: 4px 0; }
"""


def render_html(result: GateResult) -> str:
    counts = result.counts()
    exit_class = {0: "clean", 1: "breach", 2: "undecidable", 3: "undecidable"}[result.exit_code]
    out = [
        "<!doctype html><html><head><meta charset='utf-8'><title>absg gate report</title>",
        f"<style>{CSS}</style></head><body>",
        "<h1>absg gate report</h1>",
        f"<p class='sub'>Verdict at {result.policy.records:,} records, "
        f"{html.escape(result.policy.context)} limits, horizon {result.policy.horizon:,} "
        f"records, chunks of {result.policy.chunk_size}.</p>",
        f"<p class='verdict'>Exit {result.exit_code}: <span class='badge {exit_class}'>"
        f"{html.escape(MEANING[result.exit_code].split(':')[0].upper())}</span> "
        f"{html.escape(MEANING[result.exit_code].split(':', 1)[1].strip())}. "
        f"Breach {counts['breach']}, latent {counts['latent']}, clean {counts['clean']}, "
        f"undecidable {counts['undecidable']}.</p>",
        "<h2 id='coverage-against-breach-size'>Coverage against breach size</h2>",
        "<table><thead><tr>"
        + "".join(f"<th>{html.escape(h)}</th>" for h in HEADERS)
        + "</tr></thead><tbody>",
    ]
    for t, r in zip(result.triggers, _rows(result), strict=True):
        cells = []
        for i, c in enumerate(r):
            if i == 5:
                cells.append(f"<td><span class='badge {t.status}'>{html.escape(c)}</span></td>")
            elif i in (2, 3, 4):
                cells.append(f"<td class='num'>{html.escape(c)}</td>")
            else:
                cells.append(
                    f"<td><code>{html.escape(c)}</code></td>"
                    if i == 0
                    else f"<td>{html.escape(c)}</td>"
                )
        out.append("<tr>" + "".join(cells) + "</tr>")
    out.append("</tbody></table>")
    out.append("<h2 id='findings'>Findings: the breach arithmetic</h2>")
    out.append(
        "<table><thead><tr><th>Trigger</th><th>Limit</th><th>Cost per invocation</th>"
        "<th>Limit</th><th>Breaches at</th><th>Tested at</th><th>Via chain</th></tr></thead><tbody>"
    )
    for t in result.triggers:
        for f in t.findings:
            out.append(
                "<tr>"
                f"<td><code>{html.escape(t.name)}</code></td>"
                f"<td>{html.escape(LIMIT_LABELS[f.limit])}</td>"
                f"<td><code>{html.escape(f.cost_formula)}</code></td>"
                f"<td class='num'>{f.limit_value:,}</td>"
                f"<td class='num'>{f.breach_at:,}</td>"
                f"<td class='num'>{_fmt(f.tested_largest)}</td>"
                f"<td>{'yes' if f.via_chain else 'no'}</td>"
                "</tr>"
            )
    out.append("</tbody></table>")
    out.append("<h2 id='undecidable'>Undecidable: what the gate refused to cost</h2>")
    refusals = [(t, r) for t in result.triggers for r in t.refusals]
    if refusals:
        out.append("<ul class='findings'>")
        for t, r in refusals:
            out.append(
                f"<li><code>{html.escape(t.name)}</code>: {html.escape(r['reason'])}, "
                f"<code>{html.escape(r['construct'])}</code> "
                f"({html.escape(r['path'])}:{r['line']})</li>"
            )
        out.append("</ul>")
    else:
        out.append("<p>Every trigger was bounded.</p>")
    out.append("<h2 id='end'></h2></body></html>")
    return "\n".join(out) + "\n"
