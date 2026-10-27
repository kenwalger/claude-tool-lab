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


def definitions_only(source: str) -> ast.Module:
    """Keep a cell's definitions and drop the statements that act on them.

    Cells end with a checkpoint call, and some run a conversation with the
    live API. Dropping bare expressions and ``run_conversation(...)``
    assignments leaves the functions and constants, which is what tests need.

    :param source: A code cell's source.
    :returns: A module holding only the definitions.
    """
    kept: list[ast.stmt] = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.Expr):
            continue
        value = getattr(node, "value", None)
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "run_conversation":
            continue
        kept.append(node)
    return ast.Module(body=kept, type_ignores=[])


def run_cells(notebook: nbformat.NotebookNode, tags: list[str], monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Execute the definitions in tagged cells, in order, in one fresh namespace.

    The imports cell is not run, because it loads the real ``.env``. The
    namespace provides the names those cells need instead. No API call runs.

    :param notebook: A parsed notebook.
    :param tags: Tags of the cells to run, in the order to run them.
    :param monkeypatch: Used to run from the project folder, as Jupyter does.
    :returns: The namespace after running the cells.
    """
    monkeypatch.chdir(ROOT)
    namespace: dict[str, Any] = {"json": json, "Path": Path, "ToolUseBlock": ToolUseBlock}
    for tag in tags:
        exec(compile(definitions_only(tagged_source(notebook, tag)), f"<{tag}>", "exec"), namespace)
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


# Each function with a checkpoint, and the call that must end its cell.
CHECKED_CELLS: dict[str, str] = {
    "run-conversation": "lab_checks.check_part3(messages)",
    "fixed-handler": "lab_checks.check_handler(check_cellar)",
    "fixed-dispatch": "lab_checks.check_part4(merlot_messages)",
    "drink-soon-handler": "lab_checks.check_drink_soon(bottles_to_drink_soon)",
    "stretch-dispatch": "lab_checks.check_part3(drink_messages)",
    "sommelier": "lab_checks.check_part3(risotto_messages)",
}


def todo_stubs(cell_source: str) -> list[ast.FunctionDef]:
    """Find the functions in a TODO cell that the learner writes from scratch.

    ``ask_claude`` in the sommelier cell is the one exception: the learner adds
    one argument on a marked line, so it is complete code, not a stub.

    :param cell_source: A lab TODO cell's source.
    :returns: The stub function definitions.
    """
    return [
        node
        for node in ast.parse(cell_source).body
        if isinstance(node, ast.FunctionDef) and node.name != "ask_claude"
    ]


def test_lab_todo_stubs_raise_not_implemented() -> None:
    """Every TODO stub body is only a docstring and ``raise NotImplementedError("YOUR TURN: ...")``.

    Each stub is also called, so a placeholder that returns a plausible value
    and fails quietly cannot slip back in.
    """
    stubs_seen: list[str] = []
    for cell in read_notebook("lab").cells:
        if "todo" not in cell.metadata.get("tags", []):
            continue
        for stub in todo_stubs(cell.source):
            stubs_seen.append(stub.name)
            body = list(stub.body)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                body = body[1:]  # the docstring
            assert len(body) == 1 and isinstance(body[0], ast.Raise), f"{stub.name} has code besides the raise"
            raised = body[0].exc
            assert isinstance(raised, ast.Call) and getattr(raised.func, "id", None) == "NotImplementedError"
            assert isinstance(raised.args[0], ast.Constant) and raised.args[0].value.startswith("YOUR TURN: ")
            assert raised.args[0].value.endswith("This is not one of the expected failures.")

            namespace: dict[str, Any] = {"ToolUseBlock": ToolUseBlock}
            exec(compile(ast.Module(body=[stub], type_ignores=[]), f"<{stub.name}>", "exec"), namespace)
            arguments = [None] * (len(stub.args.args) - len(stub.args.defaults))
            with pytest.raises(NotImplementedError, match="^YOUR TURN: "):
                namespace[stub.name](*arguments)
    assert sorted(stubs_seen) == sorted(
        ["run_conversation", "check_cellar", "dispatch_tool", "bottles_to_drink_soon", "dispatch_tool"]
    )


def test_sommelier_todo_marks_the_system_line() -> None:
    """The lab's ask_claude is complete except for one marked line where system= goes."""
    lines = tagged_source(read_notebook("lab"), "sommelier").splitlines()
    system_lines = [line for line in lines if "system=" in line]
    assert len(system_lines) == 1
    assert system_lines[0].strip().startswith("# TODO") and "system=SOMMELIER_PROMPT" in system_lines[0]


@pytest.mark.parametrize("variant", ["solution", "lab"])
@pytest.mark.parametrize("tag", sorted(CHECKED_CELLS))
def test_checkpoint_ends_the_cell_that_defines_the_function(variant: str, tag: str) -> None:
    """Redefining a checked function always re-runs its check, because they share a cell."""
    source = tagged_source(read_notebook(variant), tag)
    assert source.rstrip().endswith(CHECKED_CELLS[tag])


@pytest.mark.parametrize("variant", ["solution", "lab"])
def test_shared_constants_live_in_given_cells(variant: str) -> None:
    """RESULT_FIELDS is defined once, at module level, in a cell the learner does not edit."""
    defining = [
        cell
        for cell in read_notebook(variant).cells
        if cell.cell_type == "code" and "RESULT_FIELDS: tuple" in cell.source
    ]
    assert len(defining) == 1
    assert "todo" not in defining[0].metadata.get("tags", [])
    assert "result-fields" in defining[0].metadata.get("tags", [])


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
    namespace = run_cells(read_notebook("solution"), ["load-cellar", "result-fields", "fixed-handler"], monkeypatch)
    assert lab_checks.check_handler(namespace["check_cellar"]) is True


def test_lab_handler_todo_fails_check_handler(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """The lab's Part 4 handler cell is a stub, and the check says so in one line."""
    namespace = run_cells(read_notebook("lab"), ["load-cellar", "result-fields", "fixed-handler"], monkeypatch)
    assert lab_checks.check_handler(namespace["check_cellar"]) is False
    assert "NotImplementedError" in capsys.readouterr().out


def test_solution_dispatch_returns_error_results(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fixed dispatch turns bad input and unknown tools into is_error results."""
    namespace = run_cells(read_notebook("solution"), ["load-cellar", "result-fields", "fixed-handler", "tool-error", "fixed-dispatch"], monkeypatch)
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
    assert lab_checks.check_drink_soon(namespace["bottles_to_drink_soon"]) is True


def test_solution_stretch_dispatch_routes_both_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """The stretch dispatch runs either tool and tolerates a missing optional argument."""
    namespace = run_cells(
        read_notebook("solution"),
        ["load-cellar", "result-fields", "fixed-handler", "tool-error", "drink-soon-handler", "stretch-dispatch"],
        monkeypatch,
    )
    dispatch = namespace["dispatch_tool"]
    soon = dispatch(tool_use("bottles_to_drink_soon", {"year": 2026}))
    assert "is_error" not in soon
    assert len(json.loads(soon["content"])["bottles"]) == 6
    assert dispatch(tool_use("check_cellar", {"varietal": "Merlot"}))["is_error"] is True


# ---------------------------------------------------------------------------
# Banners, the stretch gate, and the summary
# ---------------------------------------------------------------------------

YOUR_TURN: str = "**YOUR TURN:**"
EXPECTED_TO_FAIL: str = "**EXPECTED TO FAIL:** read the error, then move on."


def banner_before(notebook: nbformat.NotebookNode, index: int) -> str:
    """Return the Markdown cell just before a cell, or an empty string.

    :param notebook: A parsed notebook.
    :param index: The cell's position.
    :returns: The previous cell's source if it is Markdown.
    """
    previous = notebook.cells[index - 1] if index > 0 else None
    return previous.source if previous is not None and previous.cell_type == "markdown" else ""


def test_every_lab_todo_has_a_your_turn_banner() -> None:
    """Each learner cell is introduced by YOUR TURN, and nothing else is."""
    notebook = read_notebook("lab")
    todo_indexes = [i for i, cell in enumerate(notebook.cells) if "todo" in cell.metadata.get("tags", [])]
    for index in todo_indexes:
        banner = banner_before(notebook, index)
        assert banner.startswith(YOUR_TURN), notebook.cells[index].source[:60]
        if "raise NotImplementedError" in notebook.cells[index].source:
            assert banner == "**YOUR TURN:** replace the raise line with your code."
    banners = [cell for cell in notebook.cells if cell.cell_type == "markdown" and cell.source.startswith(YOUR_TURN)]
    assert len(banners) == len(todo_indexes)


def test_solution_has_no_your_turn_banners() -> None:
    """The solution has nothing for the learner to write."""
    assert all(YOUR_TURN not in cell.source for cell in read_notebook("solution").cells)


@pytest.mark.parametrize("variant", ["solution", "lab"])
def test_every_intentional_failure_has_a_banner(variant: str) -> None:
    """Each cell that fails on purpose is introduced by EXPECTED TO FAIL, and nothing else is."""
    notebook = read_notebook(variant)
    failing = [i for i, cell in enumerate(notebook.cells) if "expected-failure" in cell.metadata.get("tags", [])]
    assert len(failing) == 3
    for index in failing:
        assert banner_before(notebook, index) == EXPECTED_TO_FAIL
        assert "todo" not in notebook.cells[index].metadata.get("tags", [])
    banners = [cell for cell in notebook.cells if cell.source == EXPECTED_TO_FAIL]
    assert len(banners) == len(failing)


@pytest.mark.parametrize("variant", ["solution", "lab"])
def test_banners_are_plain_text(variant: str) -> None:
    """Banner labels are plain ASCII, with no emoji."""
    for cell in read_notebook(variant).cells:
        if cell.source.startswith((YOUR_TURN, "**EXPECTED TO FAIL:**")):
            assert cell.source.isascii()


@pytest.mark.parametrize("variant", ["solution", "lab"])
def test_summary_is_the_last_code_cell(variant: str) -> None:
    """The notebook ends by reporting every part, so no one finishes thinking they are done when they are not."""
    code_cells = [cell for cell in read_notebook(variant).cells if cell.cell_type == "code"]
    assert code_cells[-1].source == "lab_checks.summary()"


@pytest.mark.parametrize("variant", ["solution", "lab"])
def test_stretch_gate_comes_before_the_stretch(variant: str) -> None:
    """The gate runs after Part 4 and before the first stretch exercise."""
    cells = read_notebook(variant).cells
    tags = [cell.metadata.get("tags", []) for cell in cells]
    gate = next(i for i, cell_tags in enumerate(tags) if "stretch-gate" in cell_tags)
    stretch_heading = next(i for i, cell in enumerate(cells) if cell.source.startswith("## Stretch"))
    first_exercise = next(i for i, cell_tags in enumerate(tags) if "drink-soon-handler" in cell_tags)
    assert stretch_heading < gate < first_exercise
    assert cells[gate].source.rstrip().endswith("lab_checks.check_stretch_ready(check_cellar, dispatch_tool)")


PART4_TAGS: list[str] = ["load-cellar", "result-fields", "fixed-handler", "tool-error", "fixed-dispatch"]


def test_solution_passes_the_stretch_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """The finished Part 4 in solution.ipynb opens the stretch."""
    namespace = run_cells(read_notebook("solution"), PART4_TAGS, monkeypatch)
    lab_checks.check_stretch_ready(namespace["check_cellar"], namespace["dispatch_tool"])


def test_untouched_lab_stops_at_the_stretch_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the Part 4 stubs unwritten, the gate stops the run and names both functions."""
    namespace = run_cells(read_notebook("lab"), PART4_TAGS, monkeypatch)
    with pytest.raises(lab_checks.PartNotFinishedError, match="^Finish Part 4 first: ") as raised:
        lab_checks.check_stretch_ready(namespace["check_cellar"], namespace["dispatch_tool"])
    assert "check_cellar" in str(raised.value) and "dispatch_tool" in str(raised.value)


@pytest.mark.parametrize("variant", ["solution", "lab"])
def test_show_conversation_renders_claude_text_as_markdown(variant: str) -> None:
    """Claude's Markdown is rendered; the other block lines stay plain text."""
    source = tagged_source(read_notebook(variant), "helpers")
    assert "display(Markdown(block.text))" in source
    assert 'print(f"[{role}] tool_use' in source


# ---------------------------------------------------------------------------
# Pilot 3: the check_cellar hint and the sommelier check
# ---------------------------------------------------------------------------


def full_handler_hint() -> str:
    """Return the lab's last check_cellar hint, the one with the full code.

    :returns: The Markdown of that ``<details>`` block.
    """
    for cell in read_notebook("lab").cells:
        if cell.cell_type == "markdown" and "Hint 4: the full handler" in cell.source:
            return cell.source.split("Hint 4: the full handler", 1)[1]
    raise AssertionError("no full-handler hint found")


def test_full_handler_hint_is_one_function() -> None:
    """The full-code hint matches the TODO: one check_cellar, normalization inline."""
    hint = full_handler_hint()
    code_block = hint.split("```python\n", 1)[1].split("```", 1)[0]
    functions = [node.name for node in ast.parse(code_block).body if isinstance(node, ast.FunctionDef)]
    assert functions == ["check_cellar"]
    assert ".strip().casefold()" in code_block
    assert "Hint 1's normalize helper makes this tidier, and helper functions are welcome." in hint


def test_handler_todo_welcomes_helpers() -> None:
    """The TODO itself says helper functions are welcome."""
    assert "Helper functions are welcome." in tagged_source(read_notebook("lab"), "fixed-handler")


def test_sommelier_stub_has_a_placeholder() -> None:
    """The lab's sommelier cell defines an empty SOMMELIER_PROMPT under its TODO."""
    source = tagged_source(read_notebook("lab"), "sommelier")
    assert 'SOMMELIER_PROMPT: str = ""' in source
    assert source.index("# TODO: write a system prompt") < source.index('SOMMELIER_PROMPT: str = ""')


@pytest.mark.parametrize("variant", ["solution", "lab"])
def test_sommelier_cell_checks_before_the_conversation(variant: str) -> None:
    """check_sommelier runs offline before the risotto conversation spends an API call."""
    source = tagged_source(read_notebook(variant), "sommelier")
    assert source.index("lab_checks.check_sommelier(ask_claude)") < source.index("run_conversation(")


@pytest.mark.parametrize(("variant", "expected"), [("solution", True), ("lab", False)])
def test_sommelier_cell_against_check_sommelier(variant: str, expected: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    """The solution's ask_claude sends a system prompt; the lab's starting point does not."""
    import anthropic

    namespace = run_cells(read_notebook(variant), [], monkeypatch)
    namespace.update(
        client=anthropic.Anthropic(api_key="sk-ant-test-key"),
        MODEL="claude-haiku-5-5",
        TOOLS=[],
        Message=object,
    )
    exec(compile(definitions_only(tagged_source(read_notebook(variant), "sommelier")), "<sommelier>", "exec"), namespace)
    assert lab_checks.check_sommelier(namespace["ask_claude"]) is expected
