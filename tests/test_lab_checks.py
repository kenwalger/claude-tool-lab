"""Tests for lab_checks.py.

These tests never call the Claude API. They prove two things:

1. ``check_handler`` fails the planted-bug starter handler (and each partial
   fix of it) and passes the reference handler.
2. ``check_part3`` and the other checkpoints accept valid histories and
   responses, in both plain-dict and SDK-object form, and reject the specific
   mistakes learners make.
"""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

import lab_checks

CELLAR_PATH: Path = Path(__file__).resolve().parent.parent / "cellar.json"
CELLAR: list[dict] = json.loads(CELLAR_PATH.read_text(encoding="utf-8"))
RESULT_FIELDS: tuple[str, ...] = (
    "vineyard",
    "vintage",
    "region",
    "tasting_notes",
    "quantity",
    "drink_by",
)


# ---------------------------------------------------------------------------
# Handlers under test. These are copies of the notebook code on purpose: the
# tests should fail loudly if the checks stop catching the planted bug.
# ---------------------------------------------------------------------------

CELLAR_BY_VARIETAL: dict[str, list[dict]] = {}
for _bottle in CELLAR:
    CELLAR_BY_VARIETAL.setdefault(_bottle["varietal"], []).append(_bottle)


def buggy_check_cellar(varietal: str) -> dict:
    """Starter handler from lab.ipynb, including the planted bug.

    :param varietal: The grape varietal to look up.
    :returns: The bottles stored under that exact varietal string.
    """
    return {"varietal": varietal, "bottles": CELLAR_BY_VARIETAL[varietal]}


def _in_stock_varietals() -> list[str]:
    """List the varietals that have at least one bottle in stock.

    :returns: Sorted varietal names with quantity above zero.
    """
    return sorted({bottle["varietal"] for bottle in CELLAR if bottle["quantity"] > 0})


def _summarize(bottle: dict) -> dict:
    """Keep only the fields Claude needs from a bottle record.

    :param bottle: A full bottle record from cellar.json.
    :returns: A smaller dict with the result fields only.
    """
    return {field: bottle[field] for field in RESULT_FIELDS}


def reference_check_cellar(varietal: str) -> dict:
    """Reference handler from solution.ipynb.

    :param varietal: The grape varietal to look up, in any casing or spacing.
    :returns: ``{"varietal": ..., "bottles": [...]}`` with in-stock bottles only.
    :raises ValueError: If the cellar has never held this varietal.
    """
    wanted = varietal.strip().casefold()
    known = {bottle["varietal"].casefold(): bottle["varietal"] for bottle in CELLAR}
    if wanted not in known:
        available = ", ".join(_in_stock_varietals())
        raise ValueError(
            f"No varietal named {varietal!r} in the cellar. "
            f"Varietals in stock: {available}."
        )
    bottles = [
        _summarize(bottle)
        for bottle in CELLAR
        if bottle["varietal"].casefold() == wanted and bottle["quantity"] > 0
    ]
    return {"varietal": known[wanted], "bottles": bottles}


def no_normalizing_check_cellar(varietal: str) -> dict:
    """Partial fix: right shape and errors, but no case or space handling.

    :param varietal: The grape varietal to look up.
    :returns: The reference result for an exact match.
    :raises ValueError: For any string that is not an exact varietal name.
    """
    if varietal not in CELLAR_BY_VARIETAL:
        raise ValueError(f"Unknown varietal. Varietals in stock: {', '.join(_in_stock_varietals())}.")
    return reference_check_cellar(varietal)


def keeps_empty_check_cellar(varietal: str) -> dict:
    """Partial fix: normalizes input but still reports quantity 0 bottles.

    :param varietal: The grape varietal to look up.
    :returns: Every matching bottle, including ones with quantity 0.
    """
    wanted = varietal.strip().casefold()
    reference_check_cellar(varietal)  # reuse its ValueError for unknown names
    bottles = [_summarize(b) for b in CELLAR if b["varietal"].casefold() == wanted]
    return {"varietal": varietal, "bottles": bottles}


def substring_check_cellar(varietal: str) -> dict:
    """Partial fix: substring matching, so "Pinot Noir" also finds the rosé.

    :param varietal: The grape varietal to look up.
    :returns: In-stock bottles whose varietal contains the input.
    :raises ValueError: If nothing matches.
    """
    wanted = varietal.strip().casefold()
    bottles = [
        _summarize(b)
        for b in CELLAR
        if wanted in b["varietal"].casefold() and b["quantity"] > 0
    ]
    if not any(wanted in b["varietal"].casefold() for b in CELLAR):
        raise ValueError(f"Unknown varietal. Varietals in stock: {', '.join(_in_stock_varietals())}.")
    return {"varietal": varietal, "bottles": bottles}


def key_error_check_cellar(varietal: str) -> dict:
    """Partial fix: everything right except unknown varietals still raise KeyError.

    :param varietal: The grape varietal to look up.
    :returns: The reference result for known varietals.
    :raises KeyError: For a varietal the cellar has never held.
    """
    try:
        return reference_check_cellar(varietal)
    except ValueError as error:
        raise KeyError(varietal) from error


def lists_everything_check_cellar(varietal: str) -> dict:
    """Partial fix: the error message lists every varietal, including Riesling.

    :param varietal: The grape varietal to look up.
    :returns: The reference result for known varietals.
    :raises ValueError: For unknown varietals, naming all varietals ever held.
    """
    try:
        return reference_check_cellar(varietal)
    except ValueError:
        every = ", ".join(sorted({b["varietal"] for b in CELLAR}))
        raise ValueError(f"Unknown varietal. Varietals: {every}.") from None


def missing_oldest_check_cellar(varietal: str) -> dict:
    """Partial fix: drops bottles past their drink-by year, so the 2015 goes missing.

    :param varietal: The grape varietal to look up.
    :returns: The reference result without bottles whose drink_by is before 2026.
    """
    result = reference_check_cellar(varietal)
    result["bottles"] = [b for b in result["bottles"] if b["drink_by"] >= 2026]
    return result


def bare_list_check_cellar(varietal: str) -> list[dict]:
    """Partial fix: correct bottles, but returned as a bare list.

    :param varietal: The grape varietal to look up.
    :returns: The list of bottles without the wrapping dict.
    """
    return reference_check_cellar(varietal)["bottles"]


# ---------------------------------------------------------------------------
# check_handler
# ---------------------------------------------------------------------------


def test_check_handler_fails_the_planted_bug(capsys: pytest.CaptureFixture[str]) -> None:
    """The starter handler passes only the exact "Pinot Noir" case, so learners start at 1 of 5."""
    assert lab_checks.check_handler(buggy_check_cellar) is False
    output = capsys.readouterr().out
    assert "[pass] 'Pinot Noir'" in output
    assert "NOT YET: 4 of 5 cases failed" in output
    assert "KeyError" in output
    assert "2022 Winter Heron Cellars Riesling, which has quantity 0" in output


def test_check_handler_passes_the_reference(capsys: pytest.CaptureFixture[str]) -> None:
    """The reference handler passes every case."""
    assert lab_checks.check_handler(reference_check_cellar) is True
    output = capsys.readouterr().out
    assert "PASS:" in output
    assert "NOT YET:" not in output


@pytest.mark.parametrize(
    "handler",
    [
        no_normalizing_check_cellar,
        keeps_empty_check_cellar,
        substring_check_cellar,
        key_error_check_cellar,
        lists_everything_check_cellar,
        missing_oldest_check_cellar,
        bare_list_check_cellar,
    ],
    ids=lambda handler: handler.__name__,
)
def test_check_handler_catches_each_partial_fix(handler: Callable[[str], Any]) -> None:
    """Fixing only some of the bug is still NOT YET."""
    assert lab_checks.check_handler(handler) is False



def test_check_handler_lists_extra_bottles_by_vintage_and_vineyard(capsys: pytest.CaptureFixture[str]) -> None:
    """Substring matching is reported as extra bottles, named the way learners see them."""
    lab_checks.check_handler(substring_check_cellar)
    output = capsys.readouterr().out
    assert "Extra: 2024 Fernhollow Estate (Rosé of Pinot Noir)." in output
    assert "Rosé of Pinot Noir is a different wine from Pinot Noir" in output
    assert "Gamay Noir" not in output  # "pinot noir" is not a substring of "Gamay Noir", so it is not extra


def test_check_handler_lists_missing_bottles_by_vintage_and_vineyard(capsys: pytest.CaptureFixture[str]) -> None:
    """A dropped bottle is reported as missing, by vintage and vineyard."""
    lab_checks.check_handler(missing_oldest_check_cellar)
    assert "Missing: 2015 Old Mill Road Vineyards." in capsys.readouterr().out


@pytest.mark.parametrize(
    "handler",
    [
        buggy_check_cellar,
        no_normalizing_check_cellar,
        keeps_empty_check_cellar,
        substring_check_cellar,
        key_error_check_cellar,
        lists_everything_check_cellar,
        missing_oldest_check_cellar,
    ],
    ids=lambda handler: handler.__name__,
)
def test_check_handler_hints_hide_ids_and_lesson_code(
    handler: Callable[[str], Any], capsys: pytest.CaptureFixture[str]
) -> None:
    """Learners never see bottle IDs, and lesson hints explain the problem without the code."""
    lab_checks.check_handler(handler)
    output = capsys.readouterr().out
    for bottle in CELLAR:
        assert bottle["id"] not in output
    for code_hint in (".strip()", ".casefold()", "casefold", "quantity == 0", "raise ValueError("):
        assert code_hint not in output

# ---------------------------------------------------------------------------
# Message history builders. Assistant turns use SimpleNamespace blocks to
# stand in for SDK objects; user turns use plain dicts, as learners write them.
# ---------------------------------------------------------------------------


def sdk_block(**fields: Any) -> SimpleNamespace:
    """Build an object that looks like an SDK content block.

    :param fields: Attributes for the block, such as ``type`` and ``text``.
    :returns: A SimpleNamespace with those attributes.
    """
    return SimpleNamespace(**fields)


def thinking_block() -> SimpleNamespace:
    """Build an empty thinking block, as the default model returns it.

    :returns: A thinking block with empty text and a signature.
    """
    return sdk_block(type="thinking", thinking="", signature="sig-abc")


def tool_use_block(block_id: str, varietal: str) -> SimpleNamespace:
    """Build a ``tool_use`` block for ``check_cellar``.

    :param block_id: The tool use id.
    :param varietal: The varietal Claude asked for.
    :returns: An SDK-like tool_use block.
    """
    return sdk_block(type="tool_use", id=block_id, name="check_cellar", input={"varietal": varietal})


def tool_result_block(block_id: str, content: str, is_error: bool = False) -> dict:
    """Build a ``tool_result`` block the way learner code does.

    :param block_id: The ``tool_use_id`` this result answers.
    :param content: The tool output as a string.
    :param is_error: Whether the tool failed.
    :returns: A plain-dict tool_result block.
    """
    block: dict[str, Any] = {"type": "tool_result", "tool_use_id": block_id, "content": content}
    if is_error:
        block["is_error"] = True
    return block


def valid_history() -> list[dict]:
    """Build a correct Part 3 history for "Do I have any Pinot Noir?".

    :returns: A user, assistant, user, assistant message list.
    """
    result_json = json.dumps(reference_check_cellar("Pinot Noir"))
    return [
        {"role": "user", "content": "Do I have any Pinot Noir?"},
        {"role": "assistant", "content": [thinking_block(), tool_use_block("toolu_1", "Pinot Noir")]},
        {"role": "user", "content": [tool_result_block("toolu_1", result_json)]},
        {
            "role": "assistant",
            "content": [
                thinking_block(),
                sdk_block(
                    type="text",
                    text="Yes. You have the 2019 Crooked Lantern Vineyard and two others.",
                ),
            ],
        },
    ]


def merlot_history(is_error: bool = True) -> list[dict]:
    """Build a Part 4 re-run history for "Do I have any Merlot?".

    :param is_error: Whether the tool_result is flagged as an error.
    :returns: A user, assistant, user, assistant message list.
    """
    try:
        reference_check_cellar("Merlot")
    except ValueError as error:
        error_message = str(error)
    return [
        {"role": "user", "content": "Do I have any Merlot?"},
        {"role": "assistant", "content": [tool_use_block("toolu_9", "Merlot")]},
        {"role": "user", "content": [tool_result_block("toolu_9", error_message, is_error=is_error)]},
        {"role": "assistant", "content": [sdk_block(type="text", text="No Merlot, but you have Syrah.")]},
    ]


# ---------------------------------------------------------------------------
# check_part3
# ---------------------------------------------------------------------------


def test_check_part3_passes_a_valid_history(capsys: pytest.CaptureFixture[str]) -> None:
    """A correct loop passes, with SDK-object blocks and thinking blocks present."""
    assert lab_checks.check_part3(valid_history()) is True
    assert "PASS:" in capsys.readouterr().out


def test_check_part3_passes_all_dict_history() -> None:
    """The same history written entirely as plain dicts also passes."""
    history = valid_history()
    for message in history:
        if isinstance(message["content"], list):
            message["content"] = [
                vars(block) if isinstance(block, SimpleNamespace) else block
                for block in message["content"]
            ]
    assert lab_checks.check_part3(history) is True


def test_check_part3_accepts_list_style_tool_result_content() -> None:
    """``tool_result`` content may be a list of text blocks instead of a string."""
    history = valid_history()
    result = history[2]["content"][0]
    result["content"] = [{"type": "text", "text": result["content"]}]
    assert lab_checks.check_part3(history) is True


def test_check_part3_fails_missing_tool_result(capsys: pytest.CaptureFixture[str]) -> None:
    """A tool_use with no tool_result in the next user turn fails."""
    history = valid_history()
    history[2]["content"] = "Here is what the tool said."
    assert lab_checks.check_part3(history) is False
    assert "toolu_1" in capsys.readouterr().out


def test_check_part3_fails_wrong_tool_use_id() -> None:
    """A tool_result that answers a different id fails."""
    history = valid_history()
    history[2]["content"][0]["tool_use_id"] = "toolu_wrong"
    assert lab_checks.check_part3(history) is False


def test_check_part3_fails_unfinished_final_turn() -> None:
    """Stopping right after the tool_result (no final answer) fails."""
    history = valid_history()[:3]
    assert lab_checks.check_part3(history) is False


def test_check_part3_fails_final_turn_still_asking_for_tools() -> None:
    """A final assistant turn that still contains tool_use fails."""
    history = valid_history()
    history[3]["content"].append(tool_use_block("toolu_2", "Syrah"))
    assert lab_checks.check_part3(history) is False


def test_check_part3_fails_rebuilt_text_only_assistant_turn() -> None:
    """Rebuilding the tool-calling assistant turn as plain text loses the tool_use."""
    history = valid_history()
    history[1] = {"role": "assistant", "content": "Let me check the cellar."}
    assert lab_checks.check_part3(history) is False


def test_check_part3_fails_vineyard_not_in_tool_result() -> None:
    """Naming a real cellar vineyard the tool never returned fails."""
    history = valid_history()
    history[3]["content"][1].text = "Yes, the 2017 Copperleaf Ridge is lovely."
    assert lab_checks.check_part3(history) is False


def test_check_part3_fails_invented_vineyard() -> None:
    """Naming a vineyard that does not exist at all fails."""
    history = valid_history()
    history[3]["content"][1].text = "Yes, the 2018 Moonlit Acres Pinot Noir."
    assert lab_checks.check_part3(history) is False


def test_check_part3_fails_when_no_tool_was_called() -> None:
    """Answering without calling the tool fails."""
    history = [
        {"role": "user", "content": "Do I have any Pinot Noir?"},
        {"role": "assistant", "content": [sdk_block(type="text", text="Probably!")]},
    ]
    assert lab_checks.check_part3(history) is False


@pytest.mark.parametrize("not_a_history", [None, "text", [], {"role": "user"}])
def test_check_part3_handles_unfinished_todo(not_a_history: Any, capsys: pytest.CaptureFixture[str]) -> None:
    """An unfinished TODO (returning None or junk) gives a hint, not a traceback."""
    assert lab_checks.check_part3(not_a_history) is False
    assert "NOT YET:" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# check_part4
# ---------------------------------------------------------------------------


def test_check_part4_passes_error_recovery() -> None:
    """An is_error tool_result followed by a clean answer passes."""
    assert lab_checks.check_part4(merlot_history()) is True


def test_check_part4_fails_without_is_error() -> None:
    """Returning the error text without ``is_error`` fails."""
    assert lab_checks.check_part4(merlot_history(is_error=False)) is False


def test_check_part4_fails_when_loop_crashed() -> None:
    """A history that stops at the tool_use (the crash case) fails."""
    assert lab_checks.check_part4(merlot_history()[:2]) is False


# ---------------------------------------------------------------------------
# check_part1 and check_part2
# ---------------------------------------------------------------------------


def test_check_part1_passes_with_thinking_block_first() -> None:
    """A thinking block before the text is fine: blocks are found by type."""
    response = SimpleNamespace(
        stop_reason="end_turn",
        content=[thinking_block(), sdk_block(type="text", text="Hello!")],
    )
    assert lab_checks.check_part1(response) is True


def test_check_part1_fails_without_text_block() -> None:
    """A response with only a thinking block fails."""
    response = SimpleNamespace(stop_reason="end_turn", content=[thinking_block()])
    assert lab_checks.check_part1(response) is False


def test_check_part1_explains_max_tokens(capsys: pytest.CaptureFixture[str]) -> None:
    """Ending on ``max_tokens`` points the learner at ``max_tokens``."""
    response = SimpleNamespace(stop_reason="max_tokens", content=[thinking_block()])
    assert lab_checks.check_part1(response) is False
    assert "max_tokens" in capsys.readouterr().out


def test_check_part2_passes_a_tool_use_response() -> None:
    """A ``tool_use`` stop with a check_cellar call passes."""
    response = SimpleNamespace(
        stop_reason="tool_use",
        content=[thinking_block(), tool_use_block("toolu_1", "Pinot Noir")],
    )
    assert lab_checks.check_part2(response) is True


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(stop_reason="end_turn", content=[sdk_block(type="text", text="Yes!")]),
        SimpleNamespace(
            stop_reason="tool_use",
            content=[sdk_block(type="tool_use", id="toolu_1", name="other_tool", input={"varietal": "Syrah"})],
        ),
        SimpleNamespace(
            stop_reason="tool_use",
            content=[sdk_block(type="tool_use", id="toolu_1", name="check_cellar", input={})],
        ),
    ],
    ids=["no_tool_call", "wrong_tool_name", "missing_varietal"],
)
def test_check_part2_fails_bad_responses(response: SimpleNamespace) -> None:
    """No tool call, the wrong tool, or a missing varietal all fail."""
    assert lab_checks.check_part2(response) is False


# ---------------------------------------------------------------------------
# check_setup
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the setup check at a temporary project whose .venv is the kernel.

    :param tmp_path: pytest's temporary directory.
    :param monkeypatch: pytest's monkeypatch fixture.
    :returns: The temporary project root.
    """
    (tmp_path / ".venv").mkdir()
    monkeypatch.setattr(lab_checks.sys, "prefix", str(tmp_path / ".venv"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return tmp_path


def test_check_setup_passes(fake_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Key present and kernel in the project .venv passes."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    assert lab_checks.check_setup(project_root=fake_project) is True


def test_check_setup_names_missing_env_file(fake_project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """No key and no .env file points at copying .env.example."""
    assert lab_checks.check_setup(project_root=fake_project) is False
    assert ".env.example" in capsys.readouterr().out


def test_check_setup_names_unloaded_env_file(fake_project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A .env file that exists but was not loaded points at load_dotenv."""
    (fake_project / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-test\n", encoding="utf-8")
    assert lab_checks.check_setup(project_root=fake_project) is False
    assert "load_dotenv" in capsys.readouterr().out


def test_check_setup_rejects_placeholder_key(
    fake_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The placeholder from .env.example is not a real key."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "your-key-here")
    assert lab_checks.check_setup(project_root=fake_project) is False
    assert "placeholder" in capsys.readouterr().out


def test_check_setup_names_wrong_kernel(
    fake_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A kernel outside the project .venv is reported as the wrong kernel."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setattr(lab_checks.sys, "prefix", str(fake_project / "somewhere-else"))
    assert lab_checks.check_setup(project_root=fake_project) is False
    assert "kernel" in capsys.readouterr().out

