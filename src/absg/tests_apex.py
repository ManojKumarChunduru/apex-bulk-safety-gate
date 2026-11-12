"""How many records did the Apex tests actually push through each trigger?

This file exists because coverage reports which lines a test reached and not how many records
it reached them with, and the second number is the one a governor limit cares about. The reader
runs the same cost analysis over each test method, with no trigger record count in play, so
every DML statement in a test resolves to a constant number of rows: `insert new Account()` is
one, a list filled by a counted loop is the loop bound, `Test.loadData` is the row count of the
committed CSV. Anything else is recorded as unknown, never guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from absg.chain import INVOKES
from absg.cost import Analyzer
from absg.project import Project
from absg.provenance import Poly


@dataclass
class Exercise:
    """One DML statement in a test method and the number of rows it carried."""

    test_class: str
    test_method: str
    sobject: str
    operation: str
    records: int | None
    line: int
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "test": f"{self.test_class}.{self.test_method}",
            "sobject": self.sobject,
            "operation": self.operation,
            "records": self.records,
            "line": self.line,
            "note": self.note,
        }


@dataclass
class TestedSize:
    """What the tests establish about one trigger: the largest record count exercised."""

    trigger: str
    largest: int | None
    exercises: list[Exercise] = field(default_factory=list)
    unknown: int = 0  # exercises whose row count the reader could not resolve

    def to_dict(self) -> dict:
        return {
            "trigger": self.trigger,
            "largest": self.largest,
            "unknown": self.unknown,
            "exercises": [e.to_dict() for e in self.exercises],
        }


def read_exercises(project: Project) -> list[Exercise]:
    analyzer = Analyzer(project.classes, project.triggers)
    exercises: list[Exercise] = []
    for decl in sorted(project.test_classes(), key=lambda d: d.name):
        for method in sorted(decl.methods.values(), key=lambda m: m.line):
            if not method.is_test:
                continue
            cost = analyzer.analyze_method(decl, method, [], Poly.const(1), [])
            for site in cost.chains:
                records: int | None
                note = ""
                if site.resource is not None:
                    records = project.csv_rows(site.resource)
                    note = (
                        f"Test.loadData from {site.resource}.csv"
                        if records is not None
                        else (f"static resource {site.resource} not in the project")
                    )
                elif site.rows_per_statement is None or site.rows_per_statement.degree > 0:
                    records = None
                    note = "row count not bounded by the test source"
                elif site.statements.degree > 0:
                    records = None
                    note = "statement count not bounded by the test source"
                else:
                    records = site.rows_per_statement.coefficient(0)
                    note = f"{site.statements.coefficient(0)} statement(s)"
                exercises.append(
                    Exercise(
                        decl.name,
                        method.name,
                        site.sobject,
                        site.operation,
                        records,
                        site.line,
                        note,
                    )
                )
    return exercises


def tested_sizes(
    project: Project, exercises: list[Exercise] | None = None
) -> dict[str, TestedSize]:
    exercises = read_exercises(project) if exercises is None else exercises
    sizes: dict[str, TestedSize] = {}
    for name, trigger in sorted(project.triggers.items()):
        matching = [
            e
            for e in exercises
            if e.sobject.lower() == trigger.sobject.lower()
            and any(trigger.fires_on(ev) for ev in INVOKES.get(e.operation, ()))
        ]
        known = [e.records for e in matching if e.records is not None]
        sizes[name] = TestedSize(
            name,
            max(known) if known else None,
            matching,
            sum(1 for e in matching if e.records is None),
        )
    return sizes
