"""Repository hygiene: the things a reviewer notices before reading any code.

Sweeps the working tree (tracked and untracked files, so a file exempts nothing until it is
committed), checks the git history's author identity, and pins the badge URLs to the
repository's real name.
"""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
REPO = "ManojKumarChunduru/apex-bulk-safety-gate"
TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".toml",
    ".yml",
    ".yaml",
    ".json",
    ".cls",
    ".trigger",
    ".xml",
    ".csv",
    ".svg",
    ".html",
    ".txt",
    ".cfg",
    "",
}
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
FORBIDDEN_WORDS = [
    "YOUR_USERNAME",
    "USERNAME/",
    "Co-Authored-By",
    "Generated with",
    chr(0x1F916),
]
TOOL_NAMES = ["Claude", "Anthropic", "ChatGPT", "OpenAI", "Copilot"]


def tracked_and_untracked() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [ROOT / line for line in out.splitlines() if line and (ROOT / line).is_file()]


def text_files() -> list[Path]:
    return [p for p in tracked_and_untracked() if p.suffix.lower() in TEXT_SUFFIXES]


@pytest.mark.parametrize("dash", [EM_DASH, EN_DASH], ids=["em-dash", "en-dash"])
def test_no_file_in_the_working_tree_contains_a_dash_character(dash):
    offenders = []
    for path in text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if dash in text:
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []


def test_no_file_mentions_an_ai_tool_or_an_attribution_trailer():
    offenders = []
    for path in text_files():
        if path.name == "test_repo_hygiene.py":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for word in FORBIDDEN_WORDS + TOOL_NAMES:
            if word in text:
                offenders.append((path.relative_to(ROOT).as_posix(), word))
    assert offenders == []


def test_every_github_url_names_this_repository_exactly():
    pattern = re.compile(r"github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)")
    offenders = []
    for path in text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for match in pattern.findall(text):
            if match.rstrip(".") != REPO:
                offenders.append((path.relative_to(ROOT).as_posix(), match))
    assert offenders == []


def test_badge_urls_name_this_repository_exactly():
    readme = ROOT / "README.md"
    if not readme.exists():
        pytest.skip("README not written yet")
    text = readme.read_text(encoding="utf-8")
    for match in re.findall(r"img\.shields\.io/[^)\s]*", text):
        if "github" in match:
            assert REPO in match, match
    for match in re.findall(r"actions/workflows/[^)\s]*", text):
        assert "ci.yml" in match, match


def test_every_commit_is_by_the_candidate_with_no_trailers():
    log = subprocess.run(
        ["git", "log", "--format=%an <%ae>%n%(trailers)"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    identities = {line for line in log.splitlines() if line.strip()}
    assert identities == {"Manoj Kumar Chunduru <hello.manojchunduru@gmail.com>"}


def test_every_module_has_a_why_docstring():
    for path in sorted((ROOT / "src" / "absg").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert text.lstrip().startswith('"""'), path.name
        if path.name not in {"__init__.py", "__main__.py", "exit_codes.py"}:
            assert "This file exists" in text, path.name


def test_no_runtime_dependencies_are_declared():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "dependencies = []" in text


def test_no_absolute_duration_is_published_in_a_document():
    docs = [p for p in text_files() if p.suffix == ".md" and "docs/evidence" not in p.as_posix()]
    pattern = re.compile(r"\b\d+(\.\d+)?\s?(ms|milliseconds|seconds)\b")
    offenders = []
    for path in docs:
        for line in path.read_text(encoding="utf-8").splitlines():
            if pattern.search(line) and "CPU time" not in line and "wall time" not in line:
                offenders.append((path.name, line.strip()[:80]))
    assert offenders == []
