"""Tests for the generated notebooks.

These tests never call the Claude API. They check that both notebooks are
valid, committed without outputs, and identical to what
``scripts/build_notebooks.py`` produces. They also run the offline code cells
(the handlers and the dispatch function) to prove the lab notebook carries
the planted bug and the solution notebook carries the fix.
"""

import ast
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import nbformat
import pytest
from anthropic.types import ToolUseBlock

import lab_checks

ROOT: Path = Path(__file__).resolve().parent.parent
NOTEBOOK_PATHS: dict[str, Path] = {
    "solution": ROOT / "solution.ipynb",
    "lab": ROOT / "lab.ipynb",
}


def load_build_script() -> ModuleType:
    """Import ``scripts/build_notebooks.py`` without making ``scripts`` a package.

    :returns: The build script as a module.
    """
    spec = importlib.util.spec_from_file_location("build_notebooks", ROOT / "scripts" / "build_notebooks.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_notebook(variant: str) -> nbformat.NotebookNode:
    """Read one committed notebook.

    :param variant: ``"solution"`` or ``"lab"``.
    :returns: The parsed notebook.
    """
    return nbformat.read(NOTEBOOK_PATHS[variant], as_version=4)


def tagged_source(notebook: nbformat.NotebookNode, tag: str) -> str:
    """Find the one code cell with a given tag and return its source.

    :param notebook: A parsed notebook.
    :param tag: The tag to look for, such as ``"starter-handler"``.
    :returns: The cell's source code.
    """
    matches = [
        cell.source
        for cell in notebook.cells
        if cell.cell_type == "code" and tag in cell.metadata.get("tags", [])
    ]
    assert len(matches) == 1, f"expected one code cell tagged {tag!r}, found {len(matches)}"
    return matches[0]


def run_cells(notebook: nbformat.NotebookNode, tags: list[str], monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Execute tagged offline cells, in order, in one fresh namespace.

    The imports cell is not run, because it loads the real ``.env``. The
    namespace provides the names those cells need instead.

    :param notebook: A parsed notebook.
    :param tags: Tags of the cells to run, in the order to run them.
    :param monkeypatch: Used to run from the project folder, as Jupyter does.
    :returns: The namespace after running the cells.
    """
    monkeypatch.chdir(ROOT)
    namespace: dict[str, Any] = {"json": json, "Path": Path, "ToolUseBlock": ToolUseBlock}
    for tag in tags:
        exec(compile(tagged_source(notebook, tag), f"<{tag}>", "exec"), namespace)
    return namespace


def tool_use(name: str, tool_input: dict) -> ToolUseBlock:
    """Build a ``tool_use`` block like the ones in ``response.content``.

    :param name: The tool Claude asked for.
    :param tool_input: The arguments Claude sent.
    :returns: An SDK ToolUseBlock.
    """
    return ToolUseBlock.model_validate({"type": "tool_use", "id": "toolu_test", "name": name, "input": tool_input})


# ---------------------------------------------------------------------------
# Structure and hygiene
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("variant", ["solution", "lab"])
def test_notebook_is_valid(variant: str) -> None:
    """Each notebook passes nbformat validation."""
    nbformat.validate(read_notebook(variant))


@pytest.mark.parametrize("variant", ["solution", "lab"])
def test_notebook_has_no_outputs(variant: str) -> None:
    """Each notebook is committed with outputs cleared."""
    for cell in read_notebook(variant).cells:
        if cell.cell_type == "code":
            assert cell.outputs == []
            assert cell.execution_count is None


@pytest.mark.parametrize("variant", ["solution", "lab"])
def test_notebook_matches_build_script(variant: str) -> None:
    """The committed notebook is exactly what the build script generates."""
    built = load_build_script().build(variant)
    committed = read_notebook(variant)
    assert committed == built, "notebook differs from the build script: run `uv run python scripts/build_notebooks.py`"


@pytest.mark.parametrize("variant", ["solution", "lab"])
def test_code_cells_are_valid_python(variant: str) -> None:
    """Every code cell parses, so a typo in the build script cannot ship."""
    for cell in read_notebook(variant).cells:
        if cell.cell_type == "code":
            ast.parse(cell.source)


@pytest.mark.parametrize("variant", ["solution", "lab"])
def test_notebook_has_no_em_dashes(variant: str) -> None:
    """House style: no em-dashes in any cell."""
    for cell in read_notebook(variant).cells:
        assert "—" not in cell.source


@pytest.mark.parametrize("variant", ["solution", "lab"])
def test_notebook_uses_the_model_constant(variant: str) -> None:
    """The model is the single overridable constant from CLAUDE.md."""
    sources = "\n".join(cell.source for cell in read_notebook(variant).cells if cell.cell_type == "code")
    assert 'MODEL: str = os.getenv("CLAUDE_MODEL", "claude-haiku-5-5")' in sources
    assert sources.count("claude-haiku-5-5") == 1
    assert "temperature" not in sources


def test_solution_has_no_todos() -> None:
    """The reference solution is complete."""
    for cell in read_notebook("solution").cells:
        assert "TODO" not in cell.source
        assert "<details>" not in cell.source


def test_lab_todo_cells_are_tagged() -> None:
    """Every lab cell that mentions a TODO is tagged ``todo``, and the other way around."""
    for cell in read_notebook("lab").cells:
        if cell.cell_type != "code":
            continue
        has_todo = "# TODO" in cell.source
        tagged = "todo" in cell.metadata.get("tags", [])
        assert has_todo == tagged, cell.source[:80]


def test_lab_code_does_not_give_away_the_fix() -> None:
    """The lesson's code lives only in the hint cells, not in lab code cells."""
    for cell in read_notebook("lab").cells:
        if cell.cell_type == "code":
            assert "casefold" not in cell.source


def test_lab_hints_are_collapsible() -> None:
    """Every hint is a <details> block, so it stays folded until opened."""
    hint_cells = [cell for cell in read_notebook("lab").cells if "Hint" in cell.source and cell.cell_type == "markdown"]
    assert hint_cells
    for cell in hint_cells:
        if "<summary>" in cell.source:
            assert cell.source.count("<details>") == cell.source.count("</details>")
            assert cell.source.count("<details>") == cell.source.count("<summary>")


# ---------------------------------------------------------------------------
# The handlers and dispatch functions, run offline
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("variant", ["solution", "lab"])
def test_starter_handler_has_the_planted_bug(variant: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The Part 3 starter handler in both notebooks passes only exact "Pinot Noir"."""
    namespace = run_cells(read_notebook(variant), ["load-cellar", "starter-handler"], monkeypatch)
    assert lab_checks.check_handler(namespace["check_cellar"]) is False
    assert namespace["check_cellar"]("Pinot Noir")["varietal"] == "Pinot Noir"
    with pytest.raises(KeyError):
        namespace["check_cellar"]("Merlot")


@pytest.mark.parametrize("variant", ["solution", "lab"])
def test_starter_dispatch_crashes_on_merlot(variant: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The starter dispatch lets the KeyError escape, which is the Part 4 crash."""
    namespace = run_cells(read_notebook(variant), ["load-cellar", "starter-handler", "starter-dispatch"], monkeypatch)
    with pytest.raises(KeyError):
        namespace["dispatch_tool"](tool_use("check_cellar", {"varietal": "Merlot"}))


def test_solution_handler_passes_check_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fixed handler in solution.ipynb passes every offline case."""
    namespace = run_cells(read_notebook("solution"), ["load-cellar", "fixed-handler"], monkeypatch)
    assert lab_checks.check_handler(namespace["check_cellar"]) is True


def test_lab_handler_todo_still_fails_check_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    """The lab's Part 4 handler cell is a TODO that still behaves like the starter."""
    namespace = run_cells(read_notebook("lab"), ["load-cellar", "fixed-handler"], monkeypatch)
    assert lab_checks.check_handler(namespace["check_cellar"]) is False


def test_solution_dispatch_returns_error_results(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fixed dispatch turns bad input and unknown tools into is_error results."""
    namespace = run_cells(read_notebook("solution"), ["load-cellar", "fixed-handler", "fixed-dispatch"], monkeypatch)
    dispatch = namespace["dispatch_tool"]

    merlot = dispatch(tool_use("check_cellar", {"varietal": "Merlot"}))
    assert merlot["is_error"] is True
    assert merlot["tool_use_id"] == "toolu_test"
    assert "Pinot Noir" in merlot["content"] and "Riesling" not in merlot["content"]

    unknown = dispatch(tool_use("open_bottle", {}))
    assert unknown["is_error"] is True

    pinot = dispatch(tool_use("check_cellar", {"varietal": "pinot noir"}))
    assert "is_error" not in pinot
    assert len(json.loads(pinot["content"])["bottles"]) == 3


def test_solution_drink_soon_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    """The stretch tool uses its year parameter, skips empty bottles, and sorts soonest first."""
    namespace = run_cells(read_notebook("solution"), ["load-cellar", "drink-soon-handler"], monkeypatch)
    result = namespace["bottles_to_drink_soon"](2026)
    drink_by = [bottle["drink_by"] for bottle in result["bottles"]]
    assert drink_by == sorted(drink_by)
    assert all(year <= 2027 for year in drink_by)
    assert all(bottle["quantity"] > 0 for bottle in result["bottles"])
    assert len(result["bottles"]) == 6
    assert len(namespace["bottles_to_drink_soon"](2026, within_years=0)["bottles"]) == 3


def test_solution_stretch_dispatch_routes_both_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """The stretch dispatch runs either tool and tolerates a missing optional argument."""
    namespace = run_cells(
        read_notebook("solution"),
        ["load-cellar", "fixed-handler", "fixed-dispatch", "drink-soon-handler", "stretch-dispatch"],
        monkeypatch,
    )
    dispatch = namespace["dispatch_tool"]
    soon = dispatch(tool_use("bottles_to_drink_soon", {"year": 2026}))
    assert "is_error" not in soon
    assert len(json.loads(soon["content"])["bottles"]) == 6
    assert dispatch(tool_use("check_cellar", {"varietal": "Merlot"}))["is_error"] is True
