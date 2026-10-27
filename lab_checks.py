"""Checkpoint functions for the Claude tool-use lab.

Each notebook part ends with a call to one of these functions. Every check
prints ``PASS: ...`` or ``NOT YET: ...`` with a specific hint, and returns a
``bool`` so the tests in ``tests/`` can use it too.

The checks look at structure and invariants, never at Claude's exact wording,
because the model phrases its answers differently on every run.

Message content can be plain dicts (the way you write user turns) or SDK
objects (the way ``response.content`` comes back). The checks accept both.
"""

import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

PROJECT_ROOT: Path = Path(__file__).resolve().parent
CELLAR_PATH: Path = PROJECT_ROOT / "cellar.json"
PLACEHOLDER_KEY: str = "your-key-here"
TOOL_NAME: str = "check_cellar"


def load_cellar(path: Path = CELLAR_PATH) -> list[dict]:
    """Load the bottles from ``cellar.json``.

    :param path: Location of the cellar file.
    :returns: One dict per bottle.
    """
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _passed(message: str) -> bool:
    """Print a pass message.

    :param message: What went right.
    :returns: Always ``True``.
    """
    print(f"PASS: {message}")
    return True


def _not_yet(message: str) -> bool:
    """Print a hint for something that is not working yet.

    :param message: What to fix, as specifically as possible.
    :returns: Always ``False``.
    """
    print(f"NOT YET: {message}")
    return False


def _field(item: Any, name: str, default: Any = None) -> Any:
    """Read a field from a dict or an SDK object.

    :param item: A dict (``block["type"]``) or an object (``block.type``).
    :param name: The field name.
    :param default: Value to return when the field is missing.
    :returns: The field value, or ``default``.
    """
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _blocks(content: Any) -> list[Any]:
    """Turn message content into a list of content blocks.

    :param content: A string, a list of blocks, or ``None``.
    :returns: A list of blocks. A plain string becomes one text block.
    """
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, (list, tuple)):
        return list(content)
    return []


def _blocks_of_type(content: Any, block_type: str) -> list[Any]:
    """Select content blocks by their ``type`` field, never by position.

    :param content: Message or response content.
    :param block_type: For example ``"text"``, ``"tool_use"``, or ``"tool_result"``.
    :returns: The matching blocks, in order.
    """
    return [block for block in _blocks(content) if _field(block, "type") == block_type]


def _text_of(content: Any) -> str:
    """Join the text of every text block in some content.

    :param content: Message or response content.
    :returns: The combined text, or an empty string.
    """
    return "\n".join(_field(block, "text", "") or "" for block in _blocks_of_type(content, "text"))


def _tool_result_text(block: Any) -> str:
    """Get the text inside a ``tool_result`` block.

    :param block: A tool_result block whose content is a string or a list of text blocks.
    :returns: The result text, or an empty string.
    """
    content = _field(block, "content")
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        return _text_of(content)
    if content is None:
        return ""
    return str(content)


def _tool_use_ids(message: Any) -> list[str]:
    """List the ids of the ``tool_use`` blocks in one message.

    :param message: A message dict.
    :returns: The tool use ids, in order.
    """
    return [_field(block, "id") for block in _blocks_of_type(_field(message, "content"), "tool_use")]


# ---------------------------------------------------------------------------
# Part 0: setup
# ---------------------------------------------------------------------------


def check_setup(project_root: Path = PROJECT_ROOT) -> bool:
    """Confirm the environment is ready: package, kernel, and API key.

    This check never prints your key. It reads ``ANTHROPIC_API_KEY`` from the
    environment, so run the ``load_dotenv()`` cell before calling it.

    :param project_root: The lab folder, which holds ``.env`` and ``.venv``.
    :returns: ``True`` if everything is ready.
    """
    problems: list[str] = []

    try:
        import anthropic  # noqa: F401
    except ImportError:
        problems.append(
            "The anthropic package does not import in this kernel. Run `uv sync` "
            "in the project folder, then restart the kernel."
        )

    expected_prefix = os.path.normcase(str((project_root / ".venv").resolve()))
    actual_prefix = os.path.normcase(str(Path(sys.prefix).resolve()))
    if actual_prefix != expected_prefix:
        problems.append(
            f"This notebook is running on the wrong kernel ({sys.prefix}). Close "
            "Jupyter and start it again from the project folder with "
            "`uv run jupyter lab`, so it uses the project's .venv."
        )

    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        if not (project_root / ".env").exists():
            problems.append(
                "ANTHROPIC_API_KEY is not set and there is no .env file. Copy "
                ".env.example to .env, put your key after ANTHROPIC_API_KEY=, "
                "then run the load_dotenv() cell again."
            )
        else:
            problems.append(
                "A .env file exists, but ANTHROPIC_API_KEY is not set in this "
                "kernel. Run the load_dotenv() cell above, then this check again. "
                "If the key line in .env is empty, add your key first."
            )
    elif key == PLACEHOLDER_KEY:
        problems.append(
            "ANTHROPIC_API_KEY is still the placeholder from .env.example. Replace "
            "your-key-here with your real key in .env, then restart the kernel "
            "and run the cells again."
        )

    if problems:
        details = "\n".join(f"  - {problem}" for problem in problems)
        return _not_yet(f"Setup is not ready yet:\n{details}")
    return _passed(
        "The anthropic package imports, the kernel is the project's .venv, "
        "and your API key is loaded."
    )


# ---------------------------------------------------------------------------
# Part 1: hello, Claude
# ---------------------------------------------------------------------------

_STOP_REASON_HINTS: dict[str, str] = {
    "max_tokens": (
        "The reply was cut off (stop_reason is 'max_tokens'). Thinking tokens "
        "count toward max_tokens, so set max_tokens to 1024 or more and run the call again."
    ),
    "tool_use": (
        "Claude asked to use a tool (stop_reason is 'tool_use'). This call should "
        "not send any tools, so remove tools= and run it again."
    ),
    "refusal": (
        "Claude declined this request (stop_reason is 'refusal'). Try a simple, "
        "everyday message and run it again."
    ),
}


def check_part1(response: Any) -> bool:
    """Check a plain response: it finished normally and contains text.

    :param response: The object returned by ``client.messages.create(...)``.
    :returns: ``True`` if ``stop_reason`` is ``"end_turn"`` and there is a text block.
    """
    stop_reason = _field(response, "stop_reason")
    if stop_reason is None:
        return _not_yet(
            "This does not look like a response from client.messages.create(...). "
            "Pass the object that call returned, not response.content or a string."
        )
    if stop_reason != "end_turn":
        hint = _STOP_REASON_HINTS.get(stop_reason, f"Expected stop_reason 'end_turn' but got {stop_reason!r}.")
        return _not_yet(hint)
    if not _blocks_of_type(_field(response, "content"), "text"):
        return _not_yet(
            "response.content has no text block. Select blocks by their type "
            "(block.type == 'text'), never by position: a thinking block can come first."
        )
    return _passed("The response ended with 'end_turn' and contains a text block.")


# ---------------------------------------------------------------------------
# Part 2: give Claude a tool
# ---------------------------------------------------------------------------


def check_part2(response: Any) -> bool:
    """Check that Claude asked to run ``check_cellar`` with a varietal.

    :param response: The response to "Do I have any Pinot Noir?" sent with the tool attached.
    :returns: ``True`` if there is a valid ``check_cellar`` tool_use block.
    """
    stop_reason = _field(response, "stop_reason")
    if stop_reason != "tool_use":
        if stop_reason == "end_turn":
            return _not_yet(
                "Claude answered without calling the tool (stop_reason is 'end_turn'). "
                "Check that you passed tools=[CHECK_CELLAR_TOOL], and that the tool's "
                "description says it looks up bottles in the user's cellar."
            )
        hint = _STOP_REASON_HINTS.get(stop_reason, f"Expected stop_reason 'tool_use' but got {stop_reason!r}.")
        return _not_yet(hint)

    tool_uses = _blocks_of_type(_field(response, "content"), "tool_use")
    if not tool_uses:
        return _not_yet("stop_reason is 'tool_use' but response.content has no tool_use block.")

    calls = [block for block in tool_uses if _field(block, "name") == TOOL_NAME]
    if not calls:
        names = ", ".join(repr(_field(block, "name")) for block in tool_uses)
        return _not_yet(
            f"Claude called {names}, not {TOOL_NAME!r}. The name in your tool "
            f"definition must be exactly {TOOL_NAME!r}."
        )

    call = calls[0]
    tool_input = _field(call, "input")
    varietal = tool_input.get("varietal") if isinstance(tool_input, dict) else None
    if not isinstance(varietal, str) or not varietal.strip():
        return _not_yet(
            f"The tool_use input has no 'varietal' string (got {tool_input!r}). Check "
            "input_schema: one property named 'varietal' of type 'string', listed in 'required'."
        )
    return _passed(
        f"Claude asked to run {TOOL_NAME} with varietal={varietal!r} "
        f"(tool_use id {_field(call, 'id')}). Claude does not run the tool. Your code does."
    )


# ---------------------------------------------------------------------------
# Part 3 and Part 4: the conversation loop
# ---------------------------------------------------------------------------


def _history_problem(messages: Any) -> str | None:
    """Check that ``messages`` looks like a conversation history at all.

    :param messages: Whatever ``run_conversation`` returned.
    :returns: A hint if the shape is wrong, otherwise ``None``.
    """
    if not isinstance(messages, list) or not messages:
        return (
            "Expected the list of messages returned by run_conversation(...), but got "
            f"{type(messages).__name__}. If run_conversation still has its TODO, "
            "finish it and make sure it ends with `return messages`."
        )
    for message in messages:
        if _field(message, "role") not in ("user", "assistant"):
            return "Every message should be a dict with a 'role' of 'user' or 'assistant' and a 'content'."
    if _field(messages[0], "role") != "user":
        return "The conversation should start with the user's message."
    return None


def _pairing_problem(messages: list[Any]) -> str | None:
    """Check that every tool_use is answered by a matching tool_result.

    The API requires the results to arrive in the very next user message,
    each carrying the ``tool_use_id`` of the request it answers.

    :param messages: The conversation history.
    :returns: A hint for the first mismatch found, otherwise ``None``.
    """
    for index, message in enumerate(messages):
        role = _field(message, "role")
        content = _field(message, "content")

        if role == "assistant":
            requested = _tool_use_ids(message)
            if not requested or index + 1 >= len(messages):
                continue
            following = messages[index + 1]
            answered = {
                _field(block, "tool_use_id")
                for block in _blocks_of_type(_field(following, "content"), "tool_result")
            }
            for tool_use_id in requested:
                if _field(following, "role") != "user" or tool_use_id not in answered:
                    return (
                        f"Claude's tool_use {tool_use_id} has no matching tool_result in "
                        "the next user message. After running each tool, append one user "
                        "message whose content is a list of tool_result blocks, each with "
                        "'tool_use_id' set to the tool_use block's id."
                    )

        if role == "user":
            results = _blocks_of_type(content, "tool_result")
            if not results:
                continue
            previous = messages[index - 1] if index > 0 else None
            requested_before = set(_tool_use_ids(previous)) if previous is not None else set()
            for block in results:
                tool_use_id = _field(block, "tool_use_id")
                if tool_use_id not in requested_before:
                    return (
                        f"A tool_result answers tool_use_id {tool_use_id!r}, but the assistant "
                        "turn just before it has no tool_use with that id. Copy the id from "
                        "block.id. If you rebuilt the assistant turn by hand as "
                        "{'role': 'assistant', 'content': text}, the tool_use block was lost: "
                        "append response.content exactly as returned."
                    )
    return None


def _ending_problem(messages: list[Any]) -> str | None:
    """Check that the conversation ended with a finished answer from Claude.

    The history does not record ``stop_reason``, so a clean ending is inferred:
    the last message is from the assistant, has text, and asks for no tools.

    :param messages: The conversation history.
    :returns: A hint if the ending is wrong, otherwise ``None``.
    """
    last = messages[-1]
    content = _field(last, "content")
    if _field(last, "role") != "assistant":
        if _blocks_of_type(content, "tool_result"):
            return (
                "The history ends with your tool results, so Claude never answered. "
                "After appending the tool results, call the API again and append "
                "Claude's final turn before returning."
            )
        return "The last message should be Claude's final answer (role 'assistant'). Append it before returning."
    if _blocks_of_type(content, "tool_use"):
        return (
            "The last assistant turn still asks for a tool, so the conversation did not "
            "finish. Keep looping while stop_reason == 'tool_use', and make sure max_turns "
            "is not too small. If your code raised an exception here, that is the crash "
            "to fix."
        )
    if not _text_of(content).strip():
        return "The last assistant turn has no text. Append response.content from the final call."
    return None


def _tool_results(messages: list[Any]) -> list[Any]:
    """Collect every tool_result block in the history.

    :param messages: The conversation history.
    :returns: All tool_result blocks, in order.
    """
    results: list[Any] = []
    for message in messages:
        if _field(message, "role") == "user":
            results.extend(_blocks_of_type(_field(message, "content"), "tool_result"))
    return results


def _count_tool_uses(messages: list[Any]) -> int:
    """Count the tool_use blocks across all assistant turns.

    :param messages: The conversation history.
    :returns: The number of tool calls Claude made.
    """
    return sum(len(_tool_use_ids(m)) for m in messages if _field(m, "role") == "assistant")


def check_part3(messages: Any) -> bool:
    """Check a finished tool-use conversation for the loop's invariants.

    Passes when: the tool was called at least once, every tool_use has a
    matching tool_result, the conversation ended with Claude's text answer,
    and that answer names a vineyard that came back in a tool_result.

    :param messages: The history returned by ``run_conversation(...)``.
    :returns: ``True`` if every invariant holds.
    """
    problem = _history_problem(messages)
    if problem is None:
        problem = _pairing_problem(messages)
    if problem is None and _count_tool_uses(messages) == 0:
        problem = (
            "Claude never called the tool, so this answer did not come from your cellar. "
            "Send the first request with tools=[CHECK_CELLAR_TOOL] attached."
        )
    if problem is None:
        problem = _ending_problem(messages)
    if problem is not None:
        return _not_yet(problem)

    vineyards = sorted({bottle["vineyard"] for bottle in load_cellar()})
    result_text = "\n".join(_tool_result_text(block) for block in _tool_results(messages)).casefold()
    returned = [name for name in vineyards if name.casefold() in result_text]
    final_text = _text_of(_field(messages[-1], "content")).casefold()

    if not returned:
        return _not_yet(
            "No tool_result in this conversation contains a vineyard name, so Claude had "
            "nothing real to report. Put the handler's result in the tool_result content, "
            "for example with json.dumps(result)."
        )
    named = [name for name in returned if name.casefold() in final_text]
    if not named:
        elsewhere = [name for name in vineyards if name.casefold() in final_text]
        if elsewhere:
            return _not_yet(
                f"Claude's answer names {', '.join(elsewhere)}, but your tool never returned "
                "it in this conversation. Check that the tool_result content is the handler's "
                "actual output."
            )
        return _not_yet(
            "Claude's final answer does not name any vineyard your tool returned "
            f"({', '.join(returned)}). Run the conversation again. If it keeps happening, "
            "check that the tool_result content holds the full result."
        )
    return _passed(
        f"{_count_tool_uses(messages)} tool call(s), each answered by a matching tool_result, "
        f"and Claude's final answer names {named[0]}, which came from your tool."
    )


def check_part4(messages: Any) -> bool:
    """Check that the loop survived a tool error and Claude still answered.

    Used for the Merlot re-run, where no real bottle is named, so it does not
    use the vineyard check from ``check_part3``.

    :param messages: The history returned by ``run_conversation("Do I have any Merlot?")``.
    :returns: ``True`` if an ``is_error`` tool_result was sent and the conversation ended cleanly.
    """
    problem = _history_problem(messages)
    if problem is None:
        problem = _pairing_problem(messages)
    if problem is None:
        problem = _ending_problem(messages)
    if problem is not None:
        return _not_yet(problem)

    results = _tool_results(messages)
    if not results:
        return _not_yet(
            "No tool was called in this conversation. Ask about a varietal that is not "
            "in the cellar, such as Merlot, so the tool has to report an error."
        )
    if not any(_field(block, "is_error") is True for block in results):
        return _not_yet(
            "No tool_result has is_error set. When dispatch catches the ValueError, return "
            "{'type': 'tool_result', 'tool_use_id': ..., 'content': str(error), 'is_error': True}."
        )
    return _passed(
        "Claude received the error as a tool_result with is_error set and still answered. "
        "The program did not crash."
    )


# ---------------------------------------------------------------------------
# Part 4: grade the handler offline
# ---------------------------------------------------------------------------


def _bottle_keys(result: Any) -> tuple[set[tuple[str, int]] | None, str | None]:
    """Pull ``(vineyard, vintage)`` pairs out of a handler result.

    A bare list of bottles is still read, so the graders can report what is
    in it, but it also comes back with a hint about the expected shape.

    :param result: What the handler returned.
    :returns: The set of pairs (or ``None`` if unreadable) and a shape hint (or ``None``).
    """
    shape_hint: str | None = None
    if isinstance(result, list):
        bottles = result
        shape_hint = (
            "returned a bare list. Return a dict like {'varietal': ..., 'bottles': [...]} "
            "so Claude gets a labeled result."
        )
    elif isinstance(result, dict) and isinstance(result.get("bottles"), list):
        bottles = result["bottles"]
    else:
        return None, f"returned {type(result).__name__}. Return a dict with a 'bottles' list."

    keys: set[tuple[str, int]] = set()
    for bottle in bottles:
        if not isinstance(bottle, dict) or "vineyard" not in bottle or "vintage" not in bottle:
            return None, "each bottle in 'bottles' needs at least 'vineyard' and 'vintage'."
        keys.add((bottle["vineyard"], bottle["vintage"]))
    return keys, shape_hint


def _run_handler(handler: Callable[[str], Any], varietal: str) -> tuple[Any, BaseException | None]:
    """Call the handler and capture either its result or its exception.

    :param handler: The learner's ``check_cellar`` function.
    :param varietal: The input to try.
    :returns: ``(result, None)`` on success, or ``(None, error)`` if it raised.
    """
    try:
        return handler(varietal), None
    except Exception as error:  # any failure is a failed case, never a crash of the check
        return None, error


def _label(bottle_key: tuple[str, int]) -> str:
    """Name a bottle the way the learner sees it, by vintage and vineyard.

    :param bottle_key: A ``(vineyard, vintage)`` pair.
    :returns: For example ``"2019 Crooked Lantern Vineyard"``.
    """
    vineyard, vintage = bottle_key
    return f"{vintage} {vineyard}"


def check_handler(handler: Callable[[str], Any]) -> bool:
    """Run ``check_cellar`` against fixed inputs, offline, and grade each case.

    No API calls are made, so the result is the same every time. Hints say
    what is wrong and why. The notebook's hint cells show code if you need it.

    :param handler: Your ``check_cellar(varietal)`` function.
    :returns: ``True`` if every case passes.
    """
    cellar = load_cellar()
    varietal_of = {(bottle["vineyard"], bottle["vintage"]): bottle["varietal"] for bottle in cellar}
    by_id = {bottle["id"]: (bottle["vineyard"], bottle["vintage"]) for bottle in cellar}
    pinot_noir = {by_id["B001"], by_id["B002"], by_id["B009"]}
    lookalikes = {by_id["B011"], by_id["B012"]}
    out_of_stock = by_id["B008"]
    in_stock = sorted({bottle["varietal"] for bottle in cellar if bottle["quantity"] > 0})

    def describe(keys: set[tuple[str, int]]) -> str:
        """List bottles by vintage and vineyard, adding the varietal when it is not Pinot Noir.

        :param keys: The bottles to list.
        :returns: A comma-separated description.
        """
        labels = []
        for bottle_key in sorted(keys, key=lambda pair: (pair[1], pair[0])):
            varietal = varietal_of.get(bottle_key)
            if varietal is None or varietal == "Pinot Noir":
                labels.append(_label(bottle_key))
            else:
                labels.append(f"{_label(bottle_key)} ({varietal})")
        return ", ".join(labels)

    def expect_pinot_noir(varietal: str) -> str | None:
        """Grade a lookup that should return exactly the three Pinot Noir bottles.

        :param varietal: The input that was tried.
        :returns: A hint if the case fails, otherwise ``None``.
        """
        result, error = _run_handler(handler, varietal)
        if error is not None:
            return (
                f"raised {type(error).__name__}: {error}. Claude, and the people it talks to, "
                "will not always write a varietal exactly the way the cellar stores it. Input "
                "that differs only in letter case or surrounding spaces should still find the "
                "same bottles."
            )
        keys, shape_hint = _bottle_keys(result)
        if keys is None:
            return shape_hint
        if keys != pinot_noir:
            parts = ["should return exactly the three Pinot Noir bottles."]
            missing = pinot_noir - keys
            extra = keys - pinot_noir
            if missing:
                parts.append(f"Missing: {describe(missing)}.")
            if extra:
                parts.append(f"Extra: {describe(extra)}.")
            overlapping = sorted({varietal_of[bottle_key] for bottle_key in extra & lookalikes})
            if overlapping:
                parts.append(
                    f"{' and '.join(overlapping)} {'is a different wine' if len(overlapping) == 1 else 'are different wines'} "
                    "from Pinot Noir, even though the names overlap: match the whole varietal name."
                )
            return " ".join(parts)
        return shape_hint

    def expect_empty_riesling(varietal: str) -> str | None:
        """Grade the Riesling lookup, whose only bottle has quantity 0.

        :param varietal: The input that was tried.
        :returns: A hint if the case fails, otherwise ``None``.
        """
        result, error = _run_handler(handler, varietal)
        if error is not None:
            return (
                f"raised {type(error).__name__}: {error}. The cellar has held Riesling and has "
                "simply run out, so this is a valid question whose answer is \"none right now\". "
                "That is an empty result, not an error."
            )
        keys, shape_hint = _bottle_keys(result)
        if keys is None:
            return shape_hint
        if out_of_stock in keys:
            return (
                f"reported the {_label(out_of_stock)} Riesling, which has quantity 0. A bottle you "
                "have finished is no longer in the cellar, so Claude should not offer it."
            )
        if keys:
            return f"reported {describe(keys)}, but none of the cellar's Riesling is in stock."
        return shape_hint

    def expect_value_error(varietal: str) -> str | None:
        """Grade a lookup for a varietal the cellar has never held.

        :param varietal: The input that was tried.
        :returns: A hint if the case fails, otherwise ``None``.
        """
        result, error = _run_handler(handler, varietal)
        if error is None:
            return (
                f"returned a result, but the cellar has never held {varietal}. That is a "
                "question the tool cannot answer, which is different from an empty result. "
                "It should raise ValueError, so Claude learns the request was invalid."
            )
        if not isinstance(error, ValueError):
            return (
                f"raised {type(error).__name__}: {error}. Inside the conversation loop, an "
                "unexpected exception like this crashes the program before Claude can reply. "
                "A varietal the cellar has never held is invalid input, so it should raise "
                "ValueError with a message Claude can use to help the user."
            )
        message = str(error)
        missing = [name for name in in_stock if name not in message]
        if missing:
            return (
                "raised ValueError, but the message should name every varietal in stock, so "
                f"Claude can suggest something you do have. Missing: {', '.join(missing)}."
            )
        if "Riesling" in message:
            return (
                "raised ValueError, but the message names Riesling, which is out of stock, "
                "so Claude might suggest a wine you cannot open."
            )
        return None

    cases: list[tuple[str, Callable[[], str | None]]] = [
        ("'Pinot Noir' returns exactly the three Pinot Noir bottles", lambda: expect_pinot_noir("Pinot Noir")),
        ("'pinot noir' returns the same three bottles", lambda: expect_pinot_noir("pinot noir")),
        ("'  Pinot Noir  ' returns the same three bottles", lambda: expect_pinot_noir("  Pinot Noir  ")),
        ("'Riesling' returns no bottles (the only one has quantity 0)", lambda: expect_empty_riesling("Riesling")),
        ("'Merlot' raises ValueError naming the varietals in stock", lambda: expect_value_error("Merlot")),
    ]

    failures = 0
    for description, grade in cases:
        hint = grade()
        if hint is None:
            print(f"  [pass] {description}")
        else:
            failures += 1
            print(f"  [fail] {description}: {hint}")

    if failures:
        return _not_yet(f"{failures} of {len(cases)} cases failed. Fix the first failing case, then run this check again.")
    return _passed(f"All {len(cases)} handler cases pass.")
