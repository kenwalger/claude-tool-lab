"""Checkpoint functions for the Claude tool-use lab.

Each notebook part ends with a call to one of these functions. Every check
prints ``PASS: ...`` or ``NOT YET: ...`` with a specific hint, and returns a
``bool`` so the tests in ``tests/`` can use it too.

The checks look at structure and invariants, never at Claude's exact wording,
because the model phrases its answers differently on every run.

Message content can be plain dicts (the way you write user turns) or SDK
objects (the way ``response.content`` comes back). The checks accept both.
"""

import contextlib
import io
import json
import os
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

PROJECT_ROOT: Path = Path(__file__).resolve().parent
CELLAR_PATH: Path = PROJECT_ROOT / "cellar.json"
PLACEHOLDER_KEY: str = "your-key-here"
TOOL_NAME: str = "check_cellar"

# Conversation checks that have passed since the kernel started. They need the
# live API, so summary() reports them from here instead of re-running them.
SESSION_PASSES: set[str] = set()


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
    SESSION_PASSES.add("part1")
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
    SESSION_PASSES.add("part2")
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
    if not any(_field(message, "role") == "assistant" for message in messages):
        return (
            "The history holds only your message, so none of Claude's turns were recorded. "
            "Finish the TODOs in run_conversation: inside the loop and after it, append "
            "{'role': 'assistant', 'content': response.content}."
        )
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
    SESSION_PASSES.add("part3")
    called = {
        _field(block, "name")
        for message in messages
        if _field(message, "role") == "assistant"
        for block in _blocks_of_type(_field(message, "content"), "tool_use")
    }
    if "bottles_to_drink_soon" in called:
        SESSION_PASSES.add("stretch-conversation")
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
    SESSION_PASSES.add("part4")
    return _passed(
        "Claude received the error as a tool_result with is_error set and still answered. "
        "The program did not crash."
    )


# ---------------------------------------------------------------------------
# Part 4: grade the handler offline
# ---------------------------------------------------------------------------


def _bottle_keys(
    result: Any, shape: str = "{'varietal': ..., 'bottles': [...]}"
) -> tuple[set[tuple[str, int]] | None, str | None]:
    """Pull ``(vineyard, vintage)`` pairs out of a handler result.

    A bare list of bottles is still read, so the graders can report what is
    in it, but it also comes back with a hint about the expected shape.

    :param result: What the handler returned.
    :param shape: The expected result, as shown in the bare-list hint.
    :returns: The set of pairs (or ``None`` if unreadable) and a shape hint (or ``None``).
    """
    shape_hint: str | None = None
    if isinstance(result, list):
        bottles = result
        shape_hint = f"returned a bare list. Return a dict like {shape} so Claude gets a labeled result."
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


def _run_handler(handler: Callable[..., Any], *args: Any, **kwargs: Any) -> tuple[Any, BaseException | None]:
    """Call the handler and capture either its result or its exception.

    :param handler: The learner's function, such as ``check_cellar``.
    :param args: Positional arguments to pass.
    :param kwargs: Keyword arguments to pass.
    :returns: ``(result, None)`` on success, or ``(None, error)`` if it raised.
    """
    try:
        return handler(*args, **kwargs), None
    except Exception as error:  # any failure is a failed case, never a crash of the check
        return None, error


def _stub_problem(handler: Callable[..., Any], *args: Any, **kwargs: Any) -> str | None:
    """Spot a TODO stub that has not been written yet.

    A stub raises ``NotImplementedError`` on every input, so one clear hint
    helps more than a failure for every case.

    :param handler: The learner's function.
    :param args: Positional arguments for one trial call.
    :param kwargs: Keyword arguments for one trial call.
    :returns: A hint if the function is still a stub, otherwise ``None``.
    """
    _, error = _run_handler(handler, *args, **kwargs)
    if not isinstance(error, NotImplementedError):
        return None
    name = getattr(handler, "__name__", "This function")
    return (
        f"{name} still raises NotImplementedError ({error}). Write the function in this "
        "cell, delete the raise NotImplementedError line, and run the cell again."
    )


def _label(bottle_key: tuple[str, int]) -> str:
    """Name a bottle the way the learner sees it, by vintage and vineyard.

    :param bottle_key: A ``(vineyard, vintage)`` pair.
    :returns: For example ``"2019 Crooked Lantern Vineyard"``.
    """
    vineyard, vintage = bottle_key
    return f"{vintage} {vineyard}"


def _grade_handler(handler: Callable[[str], Any]) -> tuple[str | None, list[tuple[str, str | None]]]:
    """Grade ``check_cellar`` against the fixed offline cases, without printing.

    :param handler: The learner's ``check_cellar(varietal)`` function.
    :returns: A hint if the handler is still a stub (with no cases), otherwise
        ``None`` and one ``(description, hint)`` pair per case.
    """
    stub = _stub_problem(handler, "Pinot Noir")
    if stub is not None:
        return stub, []

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

    return None, [(description, grade()) for description, grade in cases]


def _report_cases(results: list[tuple[str, str | None]], noun: str) -> bool:
    """Print graded cases and an overall verdict.

    :param results: ``(description, hint)`` pairs, where a ``None`` hint means the case passed.
    :param noun: What was graded, for the pass message, such as ``"handler"``.
    :returns: ``True`` if every case passed.
    """
    failures = 0
    for description, hint in results:
        if hint is None:
            print(f"  [pass] {description}")
        else:
            failures += 1
            print(f"  [fail] {description}: {hint}")

    if failures:
        return _not_yet(f"{failures} of {len(results)} cases failed. Fix the first failing case, then run this check again.")
    return _passed(f"All {len(results)} {noun} cases pass.")


def check_handler(handler: Callable[[str], Any]) -> bool:
    """Run ``check_cellar`` against fixed inputs, offline, and grade each case.

    No API calls are made, so the result is the same every time. Hints say
    what is wrong and why. The notebook's hint cells show code if you need it.

    :param handler: Your ``check_cellar(varietal)`` function.
    :returns: ``True`` if every case passes.
    """
    stub, results = _grade_handler(handler)
    if stub is not None:
        return _not_yet(stub)
    return _report_cases(results, "handler")


# ---------------------------------------------------------------------------
# Stretch: grade bottles_to_drink_soon offline
# ---------------------------------------------------------------------------

DRINK_SOON_FIELDS: tuple[str, ...] = ("varietal", "vineyard", "vintage", "quantity", "drink_by")
DRINK_SOON_CASES: tuple[tuple[int, int], ...] = ((2026, 1), (2026, 0), (2030, 0))


def _grade_drink_soon(handler: Callable[..., Any]) -> tuple[str | None, list[tuple[str, str | None]]]:
    """Grade ``bottles_to_drink_soon`` against the fixed offline cases, without printing.

    :param handler: The learner's ``bottles_to_drink_soon(year, within_years)`` function.
    :returns: A hint if the handler is still a stub (with no cases), otherwise
        ``None`` and one ``(description, hint)`` pair per case.
    """
    stub = _stub_problem(handler, 2026, within_years=1)
    if stub is not None:
        return stub, []

    bottle_of = {(bottle["vineyard"], bottle["vintage"]): bottle for bottle in load_cellar()}
    shape = "{'year': ..., 'within_years': ..., 'bottles': [...]}"

    def due_by(deadline: int) -> set[tuple[str, int]]:
        """List the in-stock bottles due no later than a year.

        :param deadline: The last drink-by year to include.
        :returns: The matching ``(vineyard, vintage)`` pairs.
        """
        return {key for key, bottle in bottle_of.items() if bottle["quantity"] > 0 and bottle["drink_by"] <= deadline}

    def describe(keys: set[tuple[str, int]]) -> str:
        """List bottles by vintage and vineyard with their drink-by year, soonest first.

        :param keys: The bottles to list.
        :returns: A comma-separated description.
        """
        labels = []
        for key in sorted(keys, key=lambda pair: (bottle_of.get(pair, {}).get("drink_by", 0), pair[1], pair[0])):
            drink_by = bottle_of.get(key, {}).get("drink_by")
            labels.append(_label(key) if drink_by is None else f"{_label(key)} (drink by {drink_by})")
        return ", ".join(labels)

    def grade(year: int, within_years: int) -> str | None:
        """Grade one call of the handler.

        :param year: The year to pass.
        :param within_years: How many years ahead to look.
        :returns: A hint if the case fails, otherwise ``None``.
        """
        result, error = _run_handler(handler, year, within_years=within_years)
        if error is not None:
            return (
                f"raised {type(error).__name__}: {error}. Any year is a valid question, so the "
                "tool should return a result, even when no bottle is due."
            )
        keys, shape_hint = _bottle_keys(result, shape)
        if keys is None:
            return shape_hint

        deadline = year + within_years
        expected = due_by(deadline)
        if keys != expected:
            parts: list[str] = []
            this_year = date.today().year
            if year != this_year and keys == due_by(this_year + within_years):
                parts.append(
                    f"These are the bottles for {this_year}, not {year}. Use the year argument, "
                    "never today's date, so the answer is the same every time."
                )
                return " ".join(parts)
            missing = expected - keys
            extra = keys - expected
            if missing:
                parts.append(f"Missing: {describe(missing)}.")
                if any(bottle_of[key]["drink_by"] < year for key in missing):
                    parts.append(
                        "A bottle already past its drink-by year is the most urgent one to open, "
                        "so it belongs in the list."
                    )
                if any(bottle_of[key]["drink_by"] == deadline for key in missing):
                    parts.append(f"A bottle due in {deadline} is due no later than {deadline}, so include it.")
            if extra:
                parts.append(f"Extra: {describe(extra)}.")
                for key in sorted(extra, key=lambda pair: (pair[1], pair[0])):
                    if bottle_of.get(key, {}).get("quantity") == 0:
                        parts.append(f"{describe({key})} has quantity 0. A bottle you have finished is not one to open.")
                if any(bottle_of.get(key, {}).get("drink_by", 0) > deadline for key in extra):
                    parts.append(
                        f"Bottles due after {deadline} are not due yet. Look ahead exactly "
                        "within_years from the year you were given."
                    )
            return " ".join(parts)

        bottles = result if isinstance(result, list) else result["bottles"]
        absent = sorted({name for bottle in bottles for name in DRINK_SOON_FIELDS if name not in bottle})
        if absent:
            return (
                f"each bottle needs {', '.join(DRINK_SOON_FIELDS)}, so Claude can name the wine. "
                f"Missing: {', '.join(absent)}."
            )
        drink_by = [bottle["drink_by"] for bottle in bottles]
        if drink_by != sorted(drink_by):
            return (
                "has the right bottles, but they should be listed soonest first, by drink_by, "
                "so Claude leads with the most urgent one."
            )
        return shape_hint

    results: list[tuple[str, str | None]] = []
    for year, within_years in DRINK_SOON_CASES:
        description = (
            f"bottles_to_drink_soon(year={year}, within_years={within_years}) returns the "
            f"{len(due_by(year + within_years))} in-stock bottles due by {year + within_years}, soonest first"
        )
        results.append((description, grade(year, within_years)))
    return None, results


def check_drink_soon(handler: Callable[..., Any]) -> bool:
    """Run ``bottles_to_drink_soon`` against fixed years, offline, and grade each case.

    The 2030 case catches a handler that reads today's date instead of its
    ``year`` argument, and one that offers the finished Riesling.

    :param handler: Your ``bottles_to_drink_soon(year, within_years)`` function.
    :returns: ``True`` if every case passes.
    """
    stub, results = _grade_drink_soon(handler)
    if stub is not None:
        return _not_yet(stub)
    return _report_cases(results, "drink-soon")


# ---------------------------------------------------------------------------
# Part 4: probe dispatch_tool offline, and the gate before the stretch
# ---------------------------------------------------------------------------


class PartNotFinishedError(Exception):
    """Raised by the stretch gate so a notebook run stops before the stretch."""


def _dispatch_problem(dispatch: Callable[[Any], Any]) -> str | None:
    """Send ``dispatch_tool`` a fake Merlot request and check that it reports an error.

    :param dispatch: The learner's ``dispatch_tool(tool_use)`` function.
    :returns: A hint if the result is not an ``is_error`` tool_result, otherwise ``None``.
    """
    from anthropic.types import ToolUseBlock

    probe = ToolUseBlock.model_validate(
        {"type": "tool_use", "id": "toolu_offline_probe", "name": TOOL_NAME, "input": {"varietal": "Merlot"}}
    )
    result, error = _run_handler(dispatch, probe)
    if isinstance(error, NotImplementedError):
        return (
            f"dispatch_tool still raises NotImplementedError ({error}). Write it in the Part 4 "
            "dispatch cell, delete the raise line, and run that cell again."
        )
    if error is not None:
        return (
            f"dispatch_tool raised {type(error).__name__}: {error} for a Merlot request, so the "
            "conversation would crash. Catch the ValueError and return {'type': 'tool_result', "
            "'tool_use_id': tool_use.id, 'content': str(error), 'is_error': True}, for example "
            "with tool_error(tool_use, str(error))."
        )
    if _field(result, "type") != "tool_result":
        return "dispatch_tool did not return a tool_result block. Return a dict with 'type': 'tool_result'."
    if _field(result, "tool_use_id") != probe.id:
        return "dispatch_tool returned a tool_result with the wrong tool_use_id. Set 'tool_use_id': tool_use.id."
    if _field(result, "is_error") is not True:
        return (
            "dispatch_tool answered a Merlot request without 'is_error': True, so Claude cannot "
            "tell the request failed. Catch the ValueError and set 'is_error': True."
        )
    if not _tool_result_text(result).strip():
        return "dispatch_tool's error result has no content. Set 'content' to str(error), so Claude can explain."
    return None


def check_dispatch(dispatch: Callable[[Any], Any]) -> bool:
    """Check, offline, that ``dispatch_tool`` turns a bad request into an error result.

    :param dispatch: Your ``dispatch_tool(tool_use)`` function.
    :returns: ``True`` if a Merlot request comes back as an ``is_error`` tool_result.
    """
    problem = _dispatch_problem(dispatch)
    if problem is not None:
        return _not_yet(problem)
    return _passed("dispatch_tool returns an is_error tool_result for a Merlot request instead of raising.")


def check_stretch_ready(handler: Callable[[str], Any], dispatch: Callable[[Any], Any]) -> None:
    """Stop the notebook before the stretch if Part 4 is not finished.

    Runs ``check_handler``'s cases and the ``dispatch_tool`` probe offline.

    :param handler: Your ``check_cellar`` function.
    :param dispatch: Your Part 4 ``dispatch_tool`` function.
    :raises PartNotFinishedError: If either one is not finished, naming what is missing.
    """
    missing: list[str] = []
    stub, results = _grade_handler(handler)
    if stub is not None:
        missing.append("check_cellar is still the Part 4 TODO stub (it raises NotImplementedError).")
    else:
        failing = [description for description, hint in results if hint is not None]
        if failing:
            missing.append(
                f"check_cellar still fails {len(failing)} of {len(results)} check_handler cases: "
                f"{'; '.join(failing)}."
            )
    problem = _dispatch_problem(dispatch)
    if problem is not None:
        missing.append(problem)

    if missing:
        raise PartNotFinishedError(
            "Finish Part 4 first: " + " ".join(missing) + " Run the Part 4 cells again, then this one."
        )
    _passed(
        "Part 4 is finished: check_cellar passes every check_handler case, and dispatch_tool "
        "returns errors to Claude. On to the stretch."
    )


# ---------------------------------------------------------------------------
# The end of the lab: one line per part
# ---------------------------------------------------------------------------


def _quietly(check: Callable[..., bool], *args: Any) -> bool:
    """Run a check without printing its output.

    :param check: A check function from this module.
    :param args: Arguments for the check.
    :returns: What the check returned.
    """
    with contextlib.redirect_stdout(io.StringIO()):
        return check(*args)


def _notebook_namespace() -> dict[str, Any]:
    """Find the variables the notebook has defined.

    :returns: The Jupyter user namespace, or ``__main__``'s globals outside Jupyter.
    """
    try:
        from IPython import get_ipython
    except ImportError:
        get_ipython = None
    shell = get_ipython() if get_ipython is not None else None
    if shell is not None:
        return shell.user_ns
    return vars(sys.modules["__main__"])


def summary(namespace: dict[str, Any] | None = None) -> bool:
    """Print each part of the lab with PASS or NOT YET.

    Offline checks (setup, the handler, the dispatch probe, the stretch
    handler) run again on the functions as they are now. Conversation checks
    need the API, so they are reported from this session: a restarted kernel
    forgets them until you run those cells again.

    :param namespace: The notebook's variables. Leave it out in a notebook.
    :returns: ``True`` if every required part is done. The stretch is optional.
    """
    if namespace is None:
        namespace = _notebook_namespace()

    def conversation(key: str, check: str, where: str) -> str | None:
        """Report a conversation check from this session.

        :param key: The name recorded in ``SESSION_PASSES``.
        :param check: The checkpoint, for the hint.
        :param where: Which cell to run again, for the hint.
        :returns: A hint if it has not passed, otherwise ``None``.
        """
        if key in SESSION_PASSES:
            return None
        return f"{check} has not passed since the kernel started. Run the {where} again."

    def function(name: str) -> Callable[..., Any] | None:
        """Look up a function the notebook defines.

        :param name: The function name.
        :returns: The function, or ``None`` if it is not defined.
        """
        value = namespace.get(name)
        return value if callable(value) else None

    def graded(name: str, grade: Callable[[Callable[..., Any]], tuple[str | None, list[tuple[str, str | None]]]], check: str) -> str | None:
        """Re-run an offline grader on a notebook function.

        :param name: The function name.
        :param grade: ``_grade_handler`` or ``_grade_drink_soon``.
        :param check: The checkpoint, for the hint.
        :returns: A hint if any case fails, otherwise ``None``.
        """
        handler = function(name)
        if handler is None:
            return f"{name} is not defined. Run its cell."
        stub, results = grade(handler)
        if stub is not None:
            return f"{name} is still the TODO stub."
        failing = sum(1 for _, hint in results if hint is not None)
        if failing:
            return f"{failing} of {len(results)} {check} cases fail. Run that cell for the hints."
        return None

    def dispatch() -> str | None:
        """Re-run the dispatch probe.

        :returns: A hint if it fails, otherwise ``None``.
        """
        handler = function("dispatch_tool")
        if handler is None:
            return "dispatch_tool is not defined. Run its cell."
        if _dispatch_problem(handler) is not None:
            return "a Merlot request does not come back as an is_error tool_result. Run lab_checks.check_dispatch(dispatch_tool) for the details."
        return None

    def sommelier() -> str | None:
        """Check that the stretch system prompt was written.

        :returns: A hint if it is missing, otherwise ``None``.
        """
        prompt = namespace.get("SOMMELIER_PROMPT")
        if isinstance(prompt, str) and prompt.strip():
            return None
        return "SOMMELIER_PROMPT is not written yet."

    rows: list[tuple[str, bool, str | None]] = [
        ("Part 0: setup", True, None if _quietly(check_setup) else "run lab_checks.check_setup() for the details."),
        ("Part 1: your first API call", True, conversation("part1", "check_part1", "Part 1 checkpoint")),
        ("Part 2: Claude asks for the tool", True, conversation("part2", "check_part2", "Part 2 cells")),
        ("Part 3: the conversation loop", True, conversation("part3", "check_part3", "run_conversation cell")),
        ("Part 4: check_cellar handles every case", True, graded("check_cellar", _grade_handler, "check_handler")),
        ("Part 4: dispatch_tool returns errors to Claude", True, dispatch()),
        ("Part 4: the Merlot conversation recovers", True, conversation("part4", "check_part4", "Part 4 dispatch_tool cell")),
        (
            "Stretch (optional): bottles_to_drink_soon",
            False,
            graded("bottles_to_drink_soon", _grade_drink_soon, "check_drink_soon"),
        ),
        (
            "Stretch (optional): Claude uses the second tool",
            False,
            conversation("stretch-conversation", "check_part3 on a drink-soon conversation", "stretch dispatch_tool cell"),
        ),
        ("Stretch (optional): the sommelier prompt", False, sommelier()),
    ]

    print("Lab summary")
    for label, _, problem in rows:
        if problem is None:
            print(f"  PASS     {label}")
        else:
            print(f"  NOT YET  {label}: {problem}")

    not_done = [label for label, required, problem in rows if required and problem is not None]
    stretch = [problem for _, required, problem in rows if not required]
    stretch_done = sum(1 for problem in stretch if problem is None)
    if not_done:
        print(f"NOT YET: {len(not_done)} required check(s) are not done, so the lab is not finished: {'; '.join(not_done)}.")
        return False
    print(f"PASS: every required part is done. Stretch: {stretch_done} of {len(stretch)} optional checks done.")
    return True
