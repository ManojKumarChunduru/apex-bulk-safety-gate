"""Following a trigger's DML into the triggers it invokes.

This file exists because the breach is often not in the trigger you are reading. A bulkified
Account trigger that inserts one Task per account costs one DML statement; the Task trigger
behind it costs one query per task; the Account trigger therefore costs one query per account,
and breaches at the 101st account without containing a query. The chain is followed by
composing polynomials: the invoked trigger's per-invocation cost is evaluated at the rows each
statement carries, then multiplied by the number of statements. A chain that returns to a
trigger already on the stack stops at a static guard and is otherwise a refusal.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from absg.apex import TriggerDecl
from absg.cost import Analyzer, ChainSite, Cost, Refusal, Site
from absg.project import Project
from absg.provenance import Poly

# Which trigger events a DML operation invokes. Upsert and merge are costed conservatively as
# the union of the events they can fire, because the split between inserted and updated rows
# depends on data the source cannot see.
INVOKES = {
    "insert": ("insert",),
    "update": ("update",),
    "delete": ("delete",),
    "undelete": ("undelete",),
    "upsert": ("insert", "update"),
    "merge": ("update", "delete"),
    "publish": (),
}


@dataclass
class TriggerCost:
    """A trigger's own cost, plus what its chains add, kept apart so the report can say which."""

    trigger: TriggerDecl
    own: Cost
    chain_soql: Poly = field(default_factory=Poly)
    chain_sosl: Poly = field(default_factory=Poly)
    chain_dml_statements: Poly = field(default_factory=Poly)
    chain_dml_rows: Poly = field(default_factory=Poly)
    chain_refusals: list[Refusal] = field(default_factory=list)
    chain_sites: list[Site] = field(default_factory=list)

    def total(self, limit: str) -> Poly:
        own = self.own.limit_polys()[limit]
        chain = {
            "soql_queries": self.chain_soql,
            "sosl_queries": self.chain_sosl,
            "dml_statements": self.chain_dml_statements,
            "dml_rows": self.chain_dml_rows,
        }[limit]
        return own + chain

    def chain_part(self, limit: str) -> Poly:
        return {
            "soql_queries": self.chain_soql,
            "sosl_queries": self.chain_sosl,
            "dml_statements": self.chain_dml_statements,
            "dml_rows": self.chain_dml_rows,
        }[limit]

    @property
    def refusals(self) -> list[Refusal]:
        return [*self.own.refusals, *self.chain_refusals]

    @property
    def sites(self) -> list[Site]:
        return [*self.own.sites, *self.chain_sites]


class ChainResolver:
    def __init__(self, project: Project):
        self.project = project
        self.analyzer = Analyzer(project.classes, project.triggers)
        self._own: dict[str, Cost] = {}

    def own_cost(self, name: str) -> Cost:
        if name not in self._own:
            self._own[name] = self.analyzer.analyze_trigger(self.project.triggers[name])
        return self._own[name]

    def targets(self, site: ChainSite) -> list[TriggerDecl]:
        events = INVOKES.get(site.operation, ())
        return [
            t
            for t in sorted(self.project.triggers.values(), key=lambda t: t.name)
            if t.sobject.lower() == site.sobject.lower() and any(t.fires_on(e) for e in events)
        ]

    def resolve(self, name: str, stack: tuple[str, ...] = ()) -> TriggerCost:
        trigger = self.project.triggers[name]
        own = self.own_cost(name)
        result = TriggerCost(trigger, own)
        stack = (*stack, name)
        for site in own.chains:
            for target in self.targets(site):
                self._add_chain(result, site, target, stack, own.guards)
        return result

    def _add_chain(
        self,
        result: TriggerCost,
        site: ChainSite,
        target: TriggerDecl,
        stack: tuple[str, ...],
        guards: set[str],
    ) -> None:
        if target.name in stack:
            if guards:
                result.chain_sites.append(
                    Site(
                        "chain",
                        site.path,
                        site.line,
                        site.statements,
                        f"{site.operation} {site.sobject} re-enters {target.name}: "
                        f"stopped by static guard {sorted(guards)[0]}",
                    )
                )
                return
            result.chain_refusals.append(
                Refusal(
                    "reentrant",
                    f"{site.operation} {site.sobject} re-enters {target.name} with no static guard",
                    site.path,
                    site.line,
                )
            )
            return
        if site.rows_per_statement is None:
            result.chain_refusals.append(
                Refusal(
                    "unbounded_rows",
                    f"{site.operation} {site.sobject} invokes {target.name} "
                    "with rows the source does not bound",
                    site.path,
                    site.line,
                )
            )
            return
        inner = self.resolve(target.name, stack)
        rows = site.rows_per_statement
        for limit in ("soql_queries", "sosl_queries", "dml_statements", "dml_rows"):
            contribution = inner.total(limit).compose(rows) * site.statements
            if contribution.is_zero:
                continue
            attr = {
                "soql_queries": "chain_soql",
                "sosl_queries": "chain_sosl",
                "dml_statements": "chain_dml_statements",
                "dml_rows": "chain_dml_rows",
            }[limit]
            setattr(result, attr, getattr(result, attr) + contribution)
        for refusal in inner.refusals:
            result.chain_refusals.append(
                Refusal(
                    refusal.reason,
                    f"via {target.name}: {refusal.construct}",
                    refusal.path,
                    refusal.line,
                )
            )
        result.chain_sites.append(
            Site(
                "chain",
                site.path,
                site.line,
                site.statements,
                f"{site.operation} {site.sobject} invokes {target.name} "
                f"with {rows.describe()} rows per "
                f"statement: soql {inner.total('soql_queries').describe()}, "
                f"dml {inner.total('dml_statements').describe()} per invocation",
            )
        )
