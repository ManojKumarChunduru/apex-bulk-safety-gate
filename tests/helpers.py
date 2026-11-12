"""Builders for in-memory projects, so a test can state a trigger in six lines of Apex."""

from __future__ import annotations

from pathlib import Path

from absg.apex import parse_class, parse_trigger
from absg.chain import ChainResolver
from absg.limits import Policy
from absg.project import Project

FIXTURE = Path(__file__).resolve().parent.parent / "fixture"
COVERAGE = FIXTURE / "coverage" / "test-result-codecoverage.json"


def project_from(triggers: dict[str, str], classes: dict[str, str] | None = None) -> Project:
    project = Project(Path("/memory"))
    for name, source in triggers.items():
        project.triggers[name] = parse_trigger(source, f"triggers/{name}.trigger")
    for name, source in (classes or {}).items():
        project.classes[name] = parse_class(source, f"classes/{name}.cls")
    return project


def trigger(name: str, header: str, body: str) -> str:
    return f"trigger {name} on {header} {{\n{body}\n}}\n"


def cost_of(project: Project, name: str):
    return ChainResolver(project).resolve(name)


def policy(**kwargs) -> Policy:
    p = Policy()
    for key, value in kwargs.items():
        setattr(p, key, value)
    return p
