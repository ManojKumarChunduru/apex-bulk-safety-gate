"""SFDX project discovery: find the triggers, classes and static resources the gate reads.

This file exists because the gate reads a directory and nothing else. It follows
`sfdx-project.json` to the package directories, loads every `.trigger` and `.cls` under them,
and records the CSV static resources that `Test.loadData` can refer to. Files that cannot be
read are kept as load errors so the CLI can exit with the usage code and the exact file, rather
than analysing a project with a hole in it.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

from absg.apex import ApexSyntaxError, ClassDecl, TriggerDecl, parse_class, parse_trigger


class ProjectError(ValueError):
    pass


@dataclass
class Project:
    root: Path
    triggers: dict[str, TriggerDecl] = field(default_factory=dict)
    classes: dict[str, ClassDecl] = field(default_factory=dict)
    static_resources: dict[str, Path] = field(default_factory=dict)
    load_errors: list[str] = field(default_factory=list)

    def relative(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()

    def csv_rows(self, resource: str) -> int | None:
        """Row count of a CSV static resource, header excluded; None if it is not in the project."""
        path = self.static_resources.get(resource.lower())
        if path is None:
            return None
        with path.open(encoding="utf-8", newline="") as handle:
            rows = [row for row in csv.reader(handle) if any(cell.strip() for cell in row)]
        return max(len(rows) - 1, 0)

    def test_classes(self) -> list[ClassDecl]:
        return [decl for decl in self.classes.values() if decl.is_test]


def package_directories(root: Path) -> list[Path]:
    manifest = root / "sfdx-project.json"
    if not manifest.exists():
        raise ProjectError(f"{root}: no sfdx-project.json found")
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProjectError(f"{manifest}: not valid JSON ({exc})") from exc
    dirs = data.get("packageDirectories")
    if not isinstance(dirs, list) or not dirs:
        raise ProjectError(f"{manifest}: packageDirectories is missing or empty")
    paths = []
    for entry in dirs:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ProjectError(f"{manifest}: every packageDirectories entry needs a string path")
        paths.append(root / entry["path"])
    return paths


def load_project(root: str | Path) -> Project:
    root = Path(root)
    project = Project(root)
    for directory in package_directories(root):
        if not directory.is_dir():
            project.load_errors.append(
                f"package directory {project.relative(directory)} does not exist"
            )
            continue
        for path in sorted(directory.rglob("*.trigger")):
            try:
                decl = parse_trigger(path.read_text(encoding="utf-8"), project.relative(path))
            except (ApexSyntaxError, OSError, UnicodeDecodeError) as exc:
                project.load_errors.append(f"{project.relative(path)}: {exc}")
                continue
            project.triggers[decl.name] = decl
        for path in sorted(directory.rglob("*.cls")):
            try:
                decl = parse_class(path.read_text(encoding="utf-8"), project.relative(path))
            except (ApexSyntaxError, OSError, UnicodeDecodeError) as exc:
                project.load_errors.append(f"{project.relative(path)}: {exc}")
                continue
            project.classes[decl.name] = decl
        for path in sorted(directory.rglob("staticresources/*.csv")):
            project.static_resources[path.stem.lower()] = path
    if not project.triggers and not project.load_errors:
        project.load_errors.append(
            f"{project.relative(root)}: no .trigger files under any package directory"
        )
    return project
