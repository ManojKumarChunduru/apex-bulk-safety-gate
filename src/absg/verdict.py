"""One finding per trigger per limit, and the verdict a pipeline reads.

This file exists to put three numbers side by side for every trigger and limit: the record
count at which it breaches, the largest record count any test exercised, and the coverage
percentage the deploy would have accepted. The verdict at the configured record count is a
consequence of the first number; the other two are what make the first one uncomfortable. A
trigger with a refusal is undecidable whatever its bounded part says, and the exit code
distinguishes a breach from an answer the gate could not give (ADR-003).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from absg.chain import ChainResolver, TriggerCost
from absg.coverage import CoverageEntry
from absg.exit_codes import BREACH, CLEAN, UNDECIDABLE
from absg.limits import Policy, breach_size, cost_at
from absg.project import Project
from absg.tests_apex import TestedSize, sizes_by_trigger

LIMIT_ORDER = ("soql_queries", "sosl_queries", "dml_statements", "dml_rows")


@dataclass
class Finding:
    trigger: str
    limit: str
    limit_value: int
    per_invocation: int  # degree-0 coefficient
    per_record: int  # degree-1 coefficient
    higher_order: int  # sum of coefficients above degree 1
    cost_formula: str
    cost_at_records: int
    breach_at: int | None  # None: no breach within the horizon
    via_chain: bool
    tested_largest: int | None
    tested_unknown: int
    coverage_pct: float | None

    def to_dict(self) -> dict:
        return {
            "trigger": self.trigger,
            "limit": self.limit,
            "limit_value": self.limit_value,
            "per_invocation": self.per_invocation,
            "per_record": self.per_record,
            "higher_order": self.higher_order,
            "cost_formula": self.cost_formula,
            "cost_at_records": self.cost_at_records,
            "breach_at": self.breach_at,
            "via_chain": self.via_chain,
            "tested_largest": self.tested_largest,
            "tested_unknown": self.tested_unknown,
            "coverage_pct": self.coverage_pct,
        }


@dataclass
class TriggerVerdict:
    name: str
    sobject: str
    events: list[str]
    path: str
    status: str  # breach, latent, clean, undecidable
    coverage_pct: float | None
    tested: TestedSize
    findings: list[Finding]  # one per limit with a breach size within the horizon
    costs: dict[str, str]  # limit -> total formula, own plus chain
    own_costs: dict[str, str]  # limit -> formula for this trigger's own sites
    chain_costs: dict[str, str]  # limit -> formula for what its DML invokes
    refusals: list[dict]
    sites: list[dict]
    guards: list[str]

    @property
    def breaches(self) -> list[Finding]:
        return [f for f in self.findings if f.breach_at is not None and f.breach_at <= self.records]

    records: int = 200

    def smallest_breach(self) -> int | None:
        sizes = [f.breach_at for f in self.findings if f.breach_at is not None]
        return min(sizes) if sizes else None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "sobject": self.sobject,
            "events": self.events,
            "path": self.path,
            "status": self.status,
            "coverage_pct": self.coverage_pct,
            "tested": self.tested.to_dict(),
            "smallest_breach": self.smallest_breach(),
            "findings": [f.to_dict() for f in self.findings],
            "costs": self.costs,
            "own_costs": self.own_costs,
            "chain_costs": self.chain_costs,
            "refusals": self.refusals,
            "guards": self.guards,
            "sites": self.sites,
        }


@dataclass
class GateResult:
    policy: Policy
    triggers: list[TriggerVerdict]
    exit_code: int
    coverage_loaded: bool
    warnings: list[str] = field(default_factory=list)

    def by_name(self, name: str) -> TriggerVerdict:
        for t in self.triggers:
            if t.name == name:
                return t
        raise KeyError(name)

    def counts(self) -> dict[str, int]:
        return {
            "triggers": len(self.triggers),
            "breach": sum(1 for t in self.triggers if t.status == "breach"),
            "latent": sum(1 for t in self.triggers if t.status == "latent"),
            "clean": sum(1 for t in self.triggers if t.status == "clean"),
            "undecidable": sum(1 for t in self.triggers if t.status == "undecidable"),
            "findings": sum(len(t.findings) for t in self.triggers),
        }

    def to_dict(self) -> dict:
        return {
            "policy": {
                "context": self.policy.context,
                "records": self.policy.records,
                "chunk_size": self.policy.chunk_size,
                "horizon": self.policy.horizon,
                "limits": {name: self.policy.value(name) for name in LIMIT_ORDER},
            },
            "exit_code": self.exit_code,
            "coverage_loaded": self.coverage_loaded,
            "counts": self.counts(),
            "warnings": self.warnings,
            "triggers": [t.to_dict() for t in self.triggers],
        }


def _findings(
    cost: TriggerCost, policy: Policy, tested: TestedSize, coverage: CoverageEntry | None
) -> tuple[list[Finding], dict[str, str]]:
    findings: list[Finding] = []
    formulas: dict[str, str] = {}
    for limit in LIMIT_ORDER:
        poly = cost.total(limit)
        formulas[limit] = poly.describe()
        if poly.is_zero:
            continue
        value = policy.value(limit)
        size = breach_size(poly, value, policy.chunk_size, policy.horizon)
        coeffs = poly.as_dict()
        findings.append(
            Finding(
                trigger=cost.trigger.name,
                limit=limit,
                limit_value=value,
                per_invocation=coeffs.get(0, 0),
                per_record=coeffs.get(1, 0),
                higher_order=sum(v for k, v in coeffs.items() if k > 1),
                cost_formula=poly.describe(),
                cost_at_records=cost_at(poly, policy.records, policy.chunk_size),
                breach_at=size,
                via_chain=not cost.chain_part(limit).is_zero,
                tested_largest=tested.largest,
                tested_unknown=tested.unknown,
                coverage_pct=None if coverage is None else coverage.covered_percent,
            )
        )
    return [f for f in findings if f.breach_at is not None], formulas


def run_gate(
    project: Project, policy: Policy, coverage: dict[str, CoverageEntry] | None
) -> GateResult:
    resolver = ChainResolver(project)
    sizes = sizes_by_trigger(project)
    verdicts: list[TriggerVerdict] = []
    warnings: list[str] = []
    for name in sorted(project.triggers):
        cost = resolver.resolve(name)
        entry = coverage.get(name) if coverage else None
        if coverage is not None and entry is None:
            warnings.append(f"{name}: not present in the coverage report")
        findings, formulas = _findings(cost, policy, sizes[name], entry)
        if cost.refusals:
            status = "undecidable"
        elif any(f.breach_at is not None and f.breach_at <= policy.records for f in findings):
            status = "breach"
        elif findings:
            status = "latent"
        else:
            status = "clean"
        trigger = cost.trigger
        verdicts.append(
            TriggerVerdict(
                name=name,
                sobject=trigger.sobject,
                events=sorted(f"{timing} {event}" for timing, event in trigger.events),
                path=trigger.path,
                status=status,
                coverage_pct=None if entry is None else entry.covered_percent,
                tested=sizes[name],
                findings=findings,
                costs=formulas,
                own_costs={k: v.describe() for k, v in cost.own.limit_polys().items()},
                chain_costs={k: cost.chain_part(k).describe() for k in LIMIT_ORDER},
                refusals=[r.to_dict() for r in cost.refusals],
                sites=[s.to_dict() for s in cost.sites],
                guards=sorted(cost.own.guards),
                records=policy.records,
            )
        )
    if any(t.breaches for t in verdicts):
        code = BREACH
    elif any(t.status == "undecidable" for t in verdicts):
        code = UNDECIDABLE
    else:
        code = CLEAN
    return GateResult(policy, verdicts, code, coverage is not None, warnings)
