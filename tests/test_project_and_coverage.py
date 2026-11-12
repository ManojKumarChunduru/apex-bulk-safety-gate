"""Project discovery and the coverage report: what is accepted and refused at the boundary."""

import json

import pytest

from absg.coverage import CoverageError, load_coverage
from absg.project import ProjectError, load_project, package_directories
from helpers import COVERAGE, FIXTURE


def write_project(root, triggers=None, classes=None, manifest=None):
    root.mkdir(parents=True, exist_ok=True)
    (root / "sfdx-project.json").write_text(
        json.dumps(manifest or {"packageDirectories": [{"path": "force-app"}]})
    )
    base = root / "force-app" / "main" / "default"
    for name, src in (triggers or {}).items():
        (base / "triggers").mkdir(parents=True, exist_ok=True)
        (base / "triggers" / f"{name}.trigger").write_text(src)
    for name, src in (classes or {}).items():
        (base / "classes").mkdir(parents=True, exist_ok=True)
        (base / "classes" / f"{name}.cls").write_text(src)
    return root


def test_the_fixture_loads_thirteen_triggers_and_fifteen_classes():
    project = load_project(FIXTURE)
    assert project.load_errors == []
    assert len(project.triggers) == 13
    assert len(project.classes) == 15


def test_the_fixture_registers_its_csv_static_resource():
    project = load_project(FIXTURE)
    assert project.csv_rows("OrderLines") == 50


def test_csv_rows_of_a_missing_resource_is_none():
    assert load_project(FIXTURE).csv_rows("Nope") is None


def test_relative_paths_are_posix_and_relative_to_the_root():
    project = load_project(FIXTURE)
    assert project.triggers["AccountTaskTrigger"].path.startswith(
        "force-app/main/default/triggers/"
    )


def test_relative_of_a_path_outside_the_root_is_left_alone(tmp_path):
    project = load_project(FIXTURE)
    assert project.relative(tmp_path / "x") == (tmp_path / "x").as_posix()


def test_test_classes_are_the_istest_annotated_ones():
    names = sorted(d.name for d in load_project(FIXTURE).test_classes())
    assert names == [
        "AccountTriggersTest",
        "CaseTriggersTest",
        "ContactTriggersTest",
        "LeadTriggerTest",
        "OpportunityTriggersTest",
        "OrderTriggersTest",
        "TaskTriggerTest",
    ]


def test_a_missing_manifest_is_a_project_error(tmp_path):
    with pytest.raises(ProjectError):
        package_directories(tmp_path)


def test_an_invalid_manifest_is_a_project_error(tmp_path):
    (tmp_path / "sfdx-project.json").write_text("{")
    with pytest.raises(ProjectError):
        package_directories(tmp_path)


@pytest.mark.parametrize(
    "manifest", [{}, {"packageDirectories": []}, {"packageDirectories": [{"nopath": 1}]}]
)
def test_a_manifest_without_usable_package_directories_is_a_project_error(tmp_path, manifest):
    (tmp_path / "sfdx-project.json").write_text(json.dumps(manifest))
    with pytest.raises(ProjectError):
        package_directories(tmp_path)


def test_a_package_directory_that_does_not_exist_is_a_load_error(tmp_path):
    (tmp_path / "sfdx-project.json").write_text(
        json.dumps({"packageDirectories": [{"path": "missing"}]})
    )
    project = load_project(tmp_path)
    assert any("does not exist" in e for e in project.load_errors)


def test_a_project_with_no_triggers_is_a_load_error(tmp_path):
    write_project(tmp_path, classes={"X": "public class X { }"})
    assert any("no .trigger files" in e for e in load_project(tmp_path).load_errors)


def test_a_trigger_that_does_not_parse_is_a_load_error_with_its_path(tmp_path):
    write_project(tmp_path, triggers={"Bad": "trigger Bad Account { }"})
    errors = load_project(tmp_path).load_errors
    assert len(errors) == 1
    assert "Bad.trigger" in errors[0]


def test_a_class_that_does_not_parse_is_a_load_error_with_its_path(tmp_path):
    write_project(
        tmp_path,
        triggers={"T": "trigger T on Account (before insert) { }"},
        classes={"Bad": "not a class"},
    )
    errors = load_project(tmp_path).load_errors
    assert errors == ["force-app/main/default/classes/Bad.cls: no class declaration found"]


def test_the_fixture_coverage_report_loads_with_one_entry_per_trigger():
    entries = load_coverage(COVERAGE)
    for name in load_project(FIXTURE).triggers:
        assert name in entries


def test_the_no_map_prefix_is_stripped():
    assert "AccountDedupeTrigger" in load_coverage(COVERAGE)


def write_coverage(tmp_path, entries):
    path = tmp_path / "cov.json"
    path.write_text(json.dumps(entries))
    return path


GOOD = {"name": "X", "totalLines": 2, "totalCovered": 1, "coveredPercent": 50}


def test_a_minimal_entry_without_lines_is_accepted(tmp_path):
    entries = load_coverage(write_coverage(tmp_path, [GOOD]))
    assert entries["X"].covered_percent == 50.0


def test_a_consistent_lines_map_is_accepted(tmp_path):
    entries = load_coverage(write_coverage(tmp_path, [{**GOOD, "lines": {"1": 1, "2": 0}}]))
    assert entries["X"].total_covered == 1


@pytest.mark.parametrize(
    "entries",
    [
        {"name": "X"},
        [1],
        [{**GOOD, "name": ""}],
        [{"name": "X", "totalLines": 2, "totalCovered": 1}],
        [{**GOOD, "totalLines": "2"}],
        [{**GOOD, "totalCovered": 3}],
        [{**GOOD, "coveredPercent": "half"}],
        [{**GOOD, "coveredPercent": True}],
        [{**GOOD, "coveredPercent": 120}],
        [{**GOOD, "lines": [1, 0]}],
        [{**GOOD, "lines": {"1": 1}}],
        [{**GOOD, "lines": {"1": 1, "2": 1}}],
        [GOOD, GOOD],
    ],
)
def test_malformed_coverage_reports_are_refused(tmp_path, entries):
    with pytest.raises(CoverageError):
        load_coverage(write_coverage(tmp_path, entries))


def test_a_missing_coverage_file_is_refused(tmp_path):
    with pytest.raises(CoverageError):
        load_coverage(tmp_path / "missing.json")


def test_invalid_json_in_the_coverage_file_is_refused(tmp_path):
    path = tmp_path / "cov.json"
    path.write_text("[")
    with pytest.raises(CoverageError):
        load_coverage(path)
