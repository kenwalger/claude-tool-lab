"""Build ``solution.ipynb`` and ``lab.ipynb`` from one set of cell sources.

Edit this script, not the notebooks, then regenerate both:

    uv run python scripts/build_notebooks.py

Most cells are shared. Where the notebooks differ, a cell carries a
``solution`` source and a ``lab`` source: the lab gets TODOs, the planted bug
stays in place, and collapsible hint cells follow each TODO. Notebooks are
written with outputs cleared and with stable cell ids, so rebuilding without
changes produces an identical file.
"""

import textwrap
from dataclasses import dataclass, field
from pathlib import Path

import nbformat
from nbformat import NotebookNode

ROOT: Path = Path(__file__).resolve().parent.parent
OUTPUT_PATHS: dict[str, Path] = {
    "solution": ROOT / "solution.ipynb",
    "lab": ROOT / "lab.ipynb",
}
VARIANTS: tuple[str, ...] = ("solution", "lab")


@dataclass(frozen=True)
class Cell:
    """One notebook cell, possibly with a different source per notebook.

    :param kind: ``"markdown"`` or ``"code"``.
    :param solution: Source for ``solution.ipynb``, or ``None`` to leave the cell out.
    :param lab: Source for ``lab.ipynb``, or ``None`` to leave the cell out.
    :param tags: Cell tags. Tests use them to find cells; ``todo`` marks lab exercises.
    """

    kind: str
    solution: str | None
    lab: str | None
    tags: tuple[str, ...] = field(default=())


def _clean(text: str) -> str:
    """Remove the indentation and blank edges that come from writing sources inline.

    :param text: A triple-quoted source string.
    :returns: The dedented source with no leading or trailing blank lines.
    """
    return textwrap.dedent(text).strip("\n")


def md(text: str) -> Cell:
    """A Markdown cell shared by both notebooks.

    :param text: The Markdown source.
    :returns: The cell.
    """
    return Cell("markdown", _clean(text), _clean(text))


def code(text: str, *tags: str) -> Cell:
    """A code cell shared by both notebooks.

    :param text: The Python source.
    :param tags: Optional cell tags.
    :returns: The cell.
    """
    return Cell("code", _clean(text), _clean(text), tags)


def md_variant(solution: str, lab: str) -> Cell:
    """A Markdown cell whose text differs between the notebooks.

    :param solution: The solution notebook's text.
    :param lab: The lab notebook's text.
    :returns: The cell.
    """
    return Cell("markdown", _clean(solution), _clean(lab))


def exercise(solution: str, lab: str, *tags: str) -> Cell:
    """A code cell that is complete in the solution and a TODO in the lab.

    :param solution: The finished code.
    :param lab: The starting point the learner completes.
    :param tags: Tags shared by both versions. The lab version also gets ``todo``.
    :returns: The cell.
    """
    return Cell("code", _clean(solution), _clean(lab), tags)


def checkpoint(call: str) -> Cell:
    """A checkpoint code cell that calls a function from ``lab_checks``.

    :param call: The call, for example ``"lab_checks.check_part1(response)"``.
    :returns: The cell.
    """
    return code(call, "checkpoint")


# ---------------------------------------------------------------------------
# Reusable code sources. Each appears once here and wherever it is needed below.
# ---------------------------------------------------------------------------

CHECK_CELLAR_TOOL_SOLUTION = '''
    CHECK_CELLAR_TOOL: dict = {
        "name": "check_cellar",
        "description": (
            "Look up the bottles in the user's personal wine cellar for one grape "
            "varietal, such as Pinot Noir or Syrah. Returns each in-stock bottle's "
            "vineyard, vintage, region, tasting notes, quantity, and drink-by year. "
            "Use this whenever the user asks what wine they have, whether they own "
            "a varietal, or what to open. Do not answer those questions from memory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "varietal": {
                    "type": "string",
                    "description": "The grape varietal to look up, for example 'Pinot Noir'.",
                },
            },
            "required": ["varietal"],
        },
    }
'''

RUN_CONVERSATION_SOLUTION = '''
    def run_conversation(user_message: str, max_turns: int = 5) -> list[dict]:
        """Have a conversation in which Claude may call tools, and return the full history.

        :param user_message: What the user asks.
        :param max_turns: The most API calls to make, so a confused loop cannot run forever.
        :returns: Every message in the conversation, ending with Claude's final turn.
        """
        messages: list[dict] = [{"role": "user", "content": user_message}]
        response = ask_claude(messages)
        turns = 1

        while response.stop_reason == "tool_use" and turns < max_turns:
            # 1. Send Claude's turn back exactly as it came, thinking blocks included.
            messages.append({"role": "assistant", "content": response.content})

            # 2. Run every tool Claude asked for.
            tool_results: list[dict] = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_results.append(dispatch_tool(block))

            # 3. Answer all of them in one user message.
            messages.append({"role": "user", "content": tool_results})

            # 4. Let Claude continue with the results in hand.
            response = ask_claude(messages)
            turns += 1

        if response.stop_reason == "tool_use":
            print(f"Stopped after {max_turns} turns while Claude was still asking for tools.")

        # Keep Claude's final turn in the history too.
        messages.append({"role": "assistant", "content": response.content})
        return messages
'''

FIXED_HANDLER_SOLUTION = '''
    RESULT_FIELDS: tuple[str, ...] = ("vineyard", "vintage", "region", "tasting_notes", "quantity", "drink_by")


    def normalize(varietal: str) -> str:
        """Put a varietal name in a standard form so casing and spacing do not matter.

        :param varietal: A varietal name as Claude or a user wrote it.
        :returns: The name without surrounding spaces, in case-folded form.
        """
        return varietal.strip().casefold()


    def varietals_in_stock() -> list[str]:
        """List the varietals that have at least one bottle left.

        :returns: Varietal names, sorted alphabetically.
        """
        names = {bottle["varietal"] for bottle in CELLAR if bottle["quantity"] > 0}
        return sorted(names)


    def check_cellar(varietal: str) -> dict:
        """Look up the in-stock bottles in the cellar for one varietal.

        :param varietal: The grape varietal Claude asked about, in any casing or spacing.
        :returns: ``{"varietal": ..., "bottles": [...]}`` with in-stock bottles only.
        :raises ValueError: If the cellar has never held this varietal.
        """
        wanted = normalize(varietal)

        # Exact match on the normalized name, so "Pinot Noir" does not find the rosé.
        matching = [bottle for bottle in CELLAR if normalize(bottle["varietal"]) == wanted]
        if not matching:
            raise ValueError(
                f"The cellar has never held {varietal.strip()!r}. "
                f"Varietals in stock: {', '.join(varietals_in_stock())}."
            )

        # A varietal you have run out of is a valid question with an empty answer.
        bottles: list[dict] = []
        for bottle in matching:
            if bottle["quantity"] == 0:
                continue
            bottles.append({name: bottle[name] for name in RESULT_FIELDS})

        return {"varietal": matching[0]["varietal"], "bottles": bottles}
'''

TOOL_ERROR_AND_DISPATCH_SOLUTION = '''
    def tool_error(tool_use: ToolUseBlock, message: str) -> dict:
        """Build a ``tool_result`` that tells Claude the tool failed, and why.

        :param tool_use: The ``tool_use`` block that failed.
        :param message: What went wrong, in words Claude can pass on to the user.
        :returns: A ``tool_result`` block with ``"is_error": True``.
        """
        return {
            "type": "tool_result",
            "tool_use_id": tool_use.id,
            "content": message,
            "is_error": True,
        }


    def dispatch_tool(tool_use: ToolUseBlock) -> dict:
        """Run the tool Claude asked for and wrap its output as a ``tool_result`` block.

        :param tool_use: A ``tool_use`` block from ``response.content``.
        :returns: A ``tool_result`` block. If the tool failed, it has ``"is_error": True``.
        """
        if tool_use.name != "check_cellar":
            return tool_error(tool_use, f"Unknown tool: {tool_use.name}")

        try:
            result = check_cellar(tool_use.input["varietal"])
        except ValueError as error:
            return tool_error(tool_use, str(error))

        return {
            "type": "tool_result",
            "tool_use_id": tool_use.id,
            "content": json.dumps(result),
        }
'''

DRINK_SOON_HANDLER_SOLUTION = '''
    def bottles_to_drink_soon(year: int, within_years: int = 1) -> dict:
        """Find in-stock bottles that should be opened by ``year + within_years``.

        Bottles already past their drink-by year are included: they are the most urgent.

        :param year: The current year, as the user states it. Never read from the clock,
            so the answer is the same every time.
        :param within_years: How many years ahead to look.
        :returns: ``{"year": ..., "within_years": ..., "bottles": [...]}``, soonest first.
        """
        deadline = year + within_years
        soonest_first = sorted(CELLAR, key=lambda bottle: bottle["drink_by"])

        bottles: list[dict] = []
        for bottle in soonest_first:
            if bottle["quantity"] > 0 and bottle["drink_by"] <= deadline:
                bottles.append(
                    {
                        "varietal": bottle["varietal"],
                        "vineyard": bottle["vineyard"],
                        "vintage": bottle["vintage"],
                        "quantity": bottle["quantity"],
                        "drink_by": bottle["drink_by"],
                    }
                )

        return {"year": year, "within_years": within_years, "bottles": bottles}
'''

DRINK_SOON_TOOL_SOLUTION = '''
    DRINK_SOON_TOOL: dict = {
        "name": "bottles_to_drink_soon",
        "description": (
            "Find bottles in the user's wine cellar that should be opened soon: in-stock "
            "bottles whose drink-by year is no later than the given year plus within_years, "
            "including bottles already past their drink-by year. Use this when the user asks "
            "what to drink soon or what might be fading. Pass the current year the user gives. "
            "If the user has not said what year it is, ask instead of guessing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "year": {
                    "type": "integer",
                    "description": "The current year, for example 2026.",
                },
                "within_years": {
                    "type": "integer",
                    "description": "How many years ahead to look. Defaults to 1.",
                },
            },
            "required": ["year"],
        },
    }
'''

STRETCH_DISPATCH_SOLUTION = '''
    def dispatch_tool(tool_use: ToolUseBlock) -> dict:
        """Run whichever of the two tools Claude asked for, as a ``tool_result`` block.

        :param tool_use: A ``tool_use`` block from ``response.content``.
        :returns: A ``tool_result`` block. If the tool failed, it has ``"is_error": True``.
        """
        try:
            if tool_use.name == "check_cellar":
                result = check_cellar(tool_use.input["varietal"])
            elif tool_use.name == "bottles_to_drink_soon":
                # within_years is optional in the schema, so Claude may leave it out.
                result = bottles_to_drink_soon(
                    tool_use.input["year"],
                    tool_use.input.get("within_years", 1),
                )
            else:
                return tool_error(tool_use, f"Unknown tool: {tool_use.name}")
        except ValueError as error:
            return tool_error(tool_use, str(error))

        return {
            "type": "tool_result",
            "tool_use_id": tool_use.id,
            "content": json.dumps(result),
        }
'''

SOMMELIER_SOLUTION = '''
    SOMMELIER_PROMPT: str = (
        "You are a friendly sommelier helping someone choose a wine from their own cellar. "
        "Use the tools to see what they actually have, and never suggest a bottle the tools "
        "did not return. Whenever you mention a bottle, name its vintage, vineyard, and "
        "varietal. Keep answers to a few sentences."
    )


    def ask_claude(messages: list[dict]) -> Message:
        """Send the conversation so far to Claude, with the tools and the sommelier prompt.

        :param messages: The conversation history, oldest message first.
        :returns: Claude's response.
        """
        return client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SOMMELIER_PROMPT,
            tools=TOOLS,
            messages=messages,
        )
'''


def _in_hint(source: str) -> str:
    """Wrap a reusable code source as a fenced Python block for a hint cell.

    :param source: One of the ``*_SOLUTION`` sources above.
    :returns: Markdown with the code in a fence, ready to put inside ``<details>``.
    """
    return "```python\n" + _clean(source) + "\n```"


def _details(summary: str, body: str) -> str:
    """Build one collapsible hint that works in JupyterLab and on GitHub.

    The blank lines around the body let Markdown and code fences render inside the HTML.

    :param summary: The clickable label.
    :param body: Markdown shown when the hint is opened.
    :returns: A ``<details>`` block.
    """
    return f"<details>\n<summary>{summary}</summary>\n\n{body}\n\n</details>"


def _hint_cell(*blocks: str) -> Cell:
    """A lab-only Markdown cell holding one or more ``<details>`` hints.

    :param blocks: Hints built with ``_details``.
    :returns: The cell.
    """
    return Cell("markdown", None, "\n\n".join(blocks))


# ---------------------------------------------------------------------------
# The notebook, in order
# ---------------------------------------------------------------------------

OUTCOMES = """
    By the end, you will be able to:

    1. Call the Claude Messages API and read the structured response.
    2. Define a tool with a JSON schema.
    3. Write the loop that runs a tool and returns the result to Claude.
    4. Debug a tool handler that fails on realistic model input, so it returns a clear error instead of crashing.
"""

CELLS: list[Cell] = [
    md_variant(
        solution=_clean("""
            # Give Claude a Tool: a wine cellar lab (solution)

            This is the complete reference solution for `lab.ipynb`. Run it top to bottom and every
            checkpoint should print `PASS`. The one exception is on purpose: Part 4 opens by showing
            the starter code crash, exactly as it does in the lab.
        """)
        + "\n\n"
        + _clean(OUTCOMES),
        lab=_clean("""
            # Give Claude a Tool: a wine cellar lab

            In this lab you make your first call to the Claude API, then give Claude a tool that looks up
            bottles in a small wine cellar. Along the way you write the loop that runs the tool for Claude,
            and you fix a tool handler that breaks on realistic input.
        """)
        + "\n\n"
        + _clean(OUTCOMES)
        + "\n\n"
        + _clean("""
            **How this notebook works**

            - Run the cells in order with **Shift+Enter**.
            - Cells with a **TODO** comment are yours to finish.
            - Each part ends with a checkpoint that prints `PASS: ...`, or `NOT YET: ...` with a hint.
            - Stuck? Open a **Hint** below the TODO. Hints go from a nudge to the full code, and
              `solution.ipynb` has every answer.
            - With the default model, each cell that calls the API costs a small fraction of a cent.
        """),
    ),
    # ----- Part 0 -----------------------------------------------------------
    md("""
        ## Part 0: Setup (about 5 minutes)

        **What you will do:** load your API key, create a Claude client, and look at the cellar data.

        **Why it matters:** most first-day problems are environment problems: a missing key, or a
        notebook running on the wrong Python. Checking for them now keeps them from looking like code
        problems later.

        **Success looks like:** `check_setup()` prints `PASS`.
    """),
    code("""
        import json
        import os
        import traceback
        from pathlib import Path

        import anthropic
        from anthropic.types import Message, ToolUseBlock
        from dotenv import load_dotenv

        import lab_checks

        # Read ANTHROPIC_API_KEY (and the optional CLAUDE_MODEL) from the .env file.
        load_dotenv()

        # A small, fast, inexpensive model. Set CLAUDE_MODEL in .env to try another one.
        MODEL: str = os.getenv("CLAUDE_MODEL", "claude-haiku-5-5")
        print("Using model:", MODEL)
    """),
    code("""
        # The client reads ANTHROPIC_API_KEY from the environment.
        # Never paste a key into a notebook: notebooks get shared and committed.
        client = anthropic.Anthropic()
    """),
    md("""
        ### The cellar

        `cellar.json` holds 12 bottles from fictional vineyards. Everything in this lab except the
        call to Claude itself runs locally on this data, so your results are repeatable.
    """),
    code(
        """
        CELLAR: list[dict] = json.loads(Path("cellar.json").read_text(encoding="utf-8"))


        def show_cellar(bottles: list[dict]) -> None:
            \"\"\"Print bottles as a small table.

            :param bottles: Bottle records from ``cellar.json``.
            \"\"\"
            print(f"{'Vintage':<9}{'Vineyard':<27}{'Varietal':<21}{'Qty':>3}  Drink by")
            for bottle in bottles:
                print(
                    f"{bottle['vintage']:<9}{bottle['vineyard']:<27}"
                    f"{bottle['varietal']:<21}{bottle['quantity']:>3}  {bottle['drink_by']}"
                )


        show_cellar(CELLAR)
        """,
        "load-cellar",
    ),
    md("""
        ### Checkpoint

        If this prints `NOT YET`, fix what it names, then run the cells above again.
    """),
    checkpoint("lab_checks.check_setup()"),
    # ----- Part 1 -----------------------------------------------------------
    md("""
        ## Part 1: Hello, Claude (about 5 minutes)

        **What you will do:** send Claude one message and take apart what comes back.

        **Why it matters:** everything later builds on the response object. It is structured data, not
        a string, and code that treats it as a string breaks.

        **Success looks like:** `check_part1(response)` prints `PASS`.
    """),
    code("""
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            messages=[
                {"role": "user", "content": "In two sentences, why is Pinot Noir hard to grow?"},
            ],
        )

        print(response)
    """),
    md("""
        ### Reading the response

        That printout is a `Message` object. Three fields matter most:

        - `content` is a **list of content blocks**, not a string. Every block has a `type`.
        - `stop_reason` says why Claude stopped.
        - `usage` counts the tokens in and out, which is what you pay for.

        **Thinking blocks.** This model thinks before it answers when a question calls for it, so
        `content` can start with a block of type `"thinking"`. By default its `thinking` text comes back
        empty, with only a `signature`: the reasoning happened, you just do not see it. That is why code
        must select blocks **by type, never by position**. `response.content[0].text` breaks the first
        time a thinking block comes first.
    """),
    code("""
        for block in response.content:
            print("block type:", block.type)

        for block in response.content:
            if block.type == "text":
                print()
                print(block.text)

        print()
        print("stop_reason:  ", response.stop_reason)
        print("input tokens: ", response.usage.input_tokens)
        print("output tokens:", response.usage.output_tokens)
    """),
    md("""
        ### Stop reasons

        Always check `stop_reason` before you use the content.

        | `stop_reason` | What it means | What your code does |
        |---|---|---|
        | `end_turn` | Claude finished its answer. | Read the text blocks. |
        | `tool_use` | Claude wants your code to run a tool (Part 2). | Run the tool and send back the result. |
        | `max_tokens` | The reply hit your `max_tokens` cap and was cut off. Thinking counts toward the cap. | Raise `max_tokens`. |
        | `refusal` | Claude declined the request. | Tell the user; do not treat the content as an answer. |
    """),
    checkpoint("lab_checks.check_part1(response)"),
    # ----- Part 2 -----------------------------------------------------------
    md("""
        ## Part 2: Give Claude a tool (about 10 minutes)

        **What you will do:** describe a `check_cellar` tool, ask "Do I have any Pinot Noir?", and look
        at what Claude asks for.

        **Why it matters:** a tool lets Claude answer from your data instead of from memory. Claude
        never sees your cellar. It sees only what your tool returns.

        **Success looks like:** `check_part2(response)` prints `PASS`.

        ### The description is the interface

        A tool definition has three parts: a `name`, a `description`, and an `input_schema`, which is a
        JSON Schema for the arguments. Claude decides **whether** to call a tool, and **what to pass
        it**, from the description and schema alone. It cannot read your Python. A vague description
        such as "cellar tool" leads to missed or wrong calls. A good one says what the tool looks up,
        what it returns, and when to use it.
    """),
    exercise(
        solution=CHECK_CELLAR_TOOL_SOLUTION,
        lab='''
            # TODO: finish the check_cellar tool definition.
            #   1. Write a description that says what the tool looks up, what it returns,
            #      and when Claude should use it.
            #   2. Fill in input_schema: one property named "varietal", of type "string",
            #      with its own short description, and list it in "required".
            CHECK_CELLAR_TOOL: dict = {
                "name": "check_cellar",
                "description": "",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            }
        ''',
    ),
    _hint_cell(
        _details(
            "Hint 1: what a good description covers",
            "Name the data (the user's personal wine cellar), the lookup key (one grape varietal, such "
            "as Pinot Noir), what comes back (vineyard, vintage, region, tasting notes, quantity, "
            "drink-by year), and when to use it (whenever the user asks what wine they have). Telling "
            "Claude not to answer from memory helps too.",
        ),
        _details(
            "Hint 2: the shape of input_schema",
            "```python\n"
            '"input_schema": {\n'
            '    "type": "object",\n'
            '    "properties": {\n'
            '        "varietal": {"type": "string", "description": "..."},\n'
            "    },\n"
            '    "required": ["varietal"],\n'
            "},\n"
            "```",
        ),
        _details("Hint 3: the full definition", _in_hint(CHECK_CELLAR_TOOL_SOLUTION)),
    ),
    code("""
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            tools=[CHECK_CELLAR_TOOL],
            messages=[{"role": "user", "content": "Do I have any Pinot Noir?"}],
        )

        print("stop_reason:", response.stop_reason)
        for block in response.content:
            print(block)
    """),
    md("""
        ### Claude asks; your code runs

        `stop_reason` is now `"tool_use"`, and one block has type `"tool_use"`. It holds:

        - `id`: a unique id for this request. Your answer must quote it back as `tool_use_id`.
        - `name`: which tool to run.
        - `input`: the arguments, already parsed into a dict that matches your schema.

        Claude has not looked in any cellar. It has only asked. **Claude does not run the tool. Your
        code does**, and Part 3 is that code.
    """),
    code("""
        for block in response.content:
            if block.type == "tool_use":
                print("id:   ", block.id)
                print("name: ", block.name)
                print("input:", block.input)
    """),
    checkpoint("lab_checks.check_part2(response)"),
    # ----- Part 3 -----------------------------------------------------------
    md("""
        ## Part 3: Close the loop (about 15 minutes, the main exercise)

        **What you will do:** write `run_conversation`, which keeps calling Claude and running tools
        until Claude has a final answer.

        **Why it matters:** this loop is the core of every app that gives Claude tools. Once it works,
        adding a tool is just a definition and a function.

        **Success looks like:** `check_part3(messages)` prints `PASS`.

        The loop:

        1. Send the user's message with the tools attached.
        2. While `stop_reason == "tool_use"`: append Claude's turn, run each tool it asked for, append
           one user turn holding a `tool_result` for each, and call Claude again.
        3. When Claude stops asking for tools, append its final turn and return the whole history.

        ### The starter tool code

        Here is a first version of the tool handler, and a dispatch function that runs whichever tool
        Claude asks for. Read them, run the cells, and move on. You will come back to them in Part 4.
    """),
    code(
        '''
        CELLAR_BY_VARIETAL: dict[str, list[dict]] = {}
        for bottle in CELLAR:
            CELLAR_BY_VARIETAL.setdefault(bottle["varietal"], []).append(bottle)


        def check_cellar(varietal: str) -> dict:
            """Look up the bottles in the cellar for one varietal.

            :param varietal: The grape varietal Claude asked about.
            :returns: The varietal and the list of its bottles.
            """
            return {"varietal": varietal, "bottles": CELLAR_BY_VARIETAL[varietal]}
        ''',
        "starter-handler",
    ),
    code(
        '''
        def dispatch_tool(tool_use: ToolUseBlock) -> dict:
            """Run the tool Claude asked for and wrap its output as a ``tool_result`` block.

            :param tool_use: A ``tool_use`` block from ``response.content``.
            :returns: A ``tool_result`` block that answers that request.
            :raises ValueError: If Claude asks for a tool this code does not know.
            """
            if tool_use.name == "check_cellar":
                result = check_cellar(tool_use.input["varietal"])
            else:
                raise ValueError(f"Unknown tool: {tool_use.name}")

            return {
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": json.dumps(result),
            }
        ''',
        "starter-dispatch",
    ),
    md("""
        ### Two helpers

        `ask_claude` makes one API call with the tools attached, so the loop stays short.
        `show_conversation` prints a history so you can see what the loop did.
    """),
    code('''
        TOOLS: list[dict] = [CHECK_CELLAR_TOOL]


        def ask_claude(messages: list[dict]) -> Message:
            """Send the conversation so far to Claude, with the tools attached.

            :param messages: The conversation history, oldest message first.
            :returns: Claude's response.
            """
            return client.messages.create(
                model=MODEL,
                max_tokens=1024,
                tools=TOOLS,
                messages=messages,
            )


        def show_conversation(messages: list[dict]) -> None:
            """Print a conversation one block at a time.

            Blocks you build yourself are dicts; blocks from ``response.content`` are SDK
            objects. This prints both.

            :param messages: A history returned by ``run_conversation``.
            """
            for message in messages:
                role = message["role"]
                content = message["content"]
                if isinstance(content, str):
                    print(f"[{role}] {content}")
                    continue
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        label = "tool_result (error)" if block.get("is_error") else "tool_result"
                        text = str(block["content"])
                        if len(text) > 200:
                            text = text[:200] + "..."
                        print(f"[{role}] {label} for {block['tool_use_id']}: {text}")
                    elif isinstance(block, dict):
                        print(f"[{role}] {block}")
                    elif block.type == "text":
                        print(f"[{role}] {block.text}")
                    elif block.type == "tool_use":
                        print(f"[{role}] tool_use {block.name}({block.input}) id={block.id}")
                    elif block.type == "thinking":
                        print(f"[{role}] (thinking block, text hidden)")
                    else:
                        print(f"[{role}] ({block.type} block)")
    '''),
    md("""
        ### Your turn: write the loop

        Two rules the API enforces:

        - **Send Claude's turn back exactly as it came.** Append
          `{"role": "assistant", "content": response.content}`. Do not rebuild it as
          `{"role": "assistant", "content": text}`: that throws away the `tool_use` block your result
          answers, and the thinking blocks the model needs back unchanged.
        - **Answer every tool request in the very next user message:** one user message, holding one
          `tool_result` per `tool_use`, each with the matching `tool_use_id`. `dispatch_tool` already
          builds those `tool_result` blocks for you.
    """),
    exercise(
        solution=RUN_CONVERSATION_SOLUTION,
        lab='''
            def run_conversation(user_message: str, max_turns: int = 5) -> list[dict]:
                """Have a conversation in which Claude may call tools, and return the full history.

                :param user_message: What the user asks.
                :param max_turns: The most API calls to make, so a confused loop cannot run forever.
                :returns: Every message in the conversation, ending with Claude's final turn.
                """
                messages: list[dict] = [{"role": "user", "content": user_message}]
                response = ask_claude(messages)
                turns = 1

                # TODO: loop while response.stop_reason == "tool_use" and turns < max_turns:
                #   1. Append Claude's turn: {"role": "assistant", "content": response.content}.
                #      Use response.content exactly as returned. Do not rebuild it from the text.
                #   2. For each block in response.content whose block.type is "tool_use",
                #      call dispatch_tool(block) and collect the tool_result it returns.
                #   3. Append ONE user message whose content is the list of tool_results.
                #   4. Call ask_claude(messages) again, store it in response, and add 1 to turns.

                if response.stop_reason == "tool_use":
                    print(f"Stopped after {max_turns} turns while Claude was still asking for tools.")

                # TODO: append Claude's final turn the same way as step 1.

                return messages
        ''',
    ),
    _hint_cell(
        _details(
            "Hint 1: the shape of the loop",
            "```python\n"
            'while response.stop_reason == "tool_use" and turns < max_turns:\n'
            "    messages.append(...)        # step 1\n"
            "    tool_results = []\n"
            "    for block in response.content:\n"
            "        ...                     # step 2\n"
            "    messages.append(...)        # step 3\n"
            "    response = ask_claude(messages)\n"
            "    turns += 1                  # step 4\n"
            "```",
        ),
        _details("Hint 2: the full function", _in_hint(RUN_CONVERSATION_SOLUTION)),
    ),
    code("""
        messages = run_conversation("Do I have any Pinot Noir?")
        show_conversation(messages)
    """),
    md("""
        ### Checkpoint

        This check looks at the shape of the conversation, never at Claude's exact words: the tool was
        called, every `tool_use` has a matching `tool_result`, the conversation ended with Claude's
        answer, and that answer names a vineyard your tool actually returned.
    """),
    checkpoint("lab_checks.check_part3(messages)"),
    # ----- Part 4 -----------------------------------------------------------
    md("""
        ## Part 4: When the model surprises you (about 10 minutes)

        **What you will do:** ask about a wine you do not have, watch the program crash, reproduce the
        failure without the API, and fix both the handler and the dispatch function.

        **Why it matters:** Claude passes whatever input seems right to it, and users ask about
        anything. A tool that works only on the inputs you imagined will fail in real use. The fix is a
        tool that returns a clear error, so Claude can explain the problem to the user.

        **Success looks like:** `check_handler(check_cellar)` and `check_part4(merlot_messages)` both
        print `PASS`.
    """),
    code("""
        # This is expected to fail. The try/except is here only so the notebook keeps
        # running and you can read the traceback.
        try:
            merlot_messages = run_conversation("Do I have any Merlot?")
            show_conversation(merlot_messages)
        except Exception:
            traceback.print_exc()
    """),
    md("""
        ### Read the traceback

        Read it from the bottom up. The last line is the error: `KeyError: 'Merlot'`. The lines above
        it show the path: `check_cellar` looked up the key, `dispatch_tool` called `check_cellar`, and
        `run_conversation` called `dispatch_tool`. Nothing caught the error, so the whole conversation
        died, and Claude never got the chance to say "no Merlot, but here is what you have."

        The fastest way to debug a tool is to call it directly. You do not need the API for that.
    """),
    code('''
        def try_handler(varietal: str) -> None:
            """Call check_cellar directly and print what happens.

            :param varietal: The input to try.
            """
            try:
                result = check_cellar(varietal)
            except Exception as error:
                print(f"{varietal!r:>18}: raised {type(error).__name__}: {error}")
                return
            quantities = [bottle["quantity"] for bottle in result["bottles"]]
            print(f"{varietal!r:>18}: {len(quantities)} bottle(s), quantities {quantities}")


        for varietal in ["Pinot Noir", "Merlot", "pinot noir", "  Pinot Noir  ", "Riesling"]:
            try_handler(varietal)
    '''),
    md("""
        ### Three bugs, and you saw only one of them live

        - **`'Merlot'`**: the cellar has never held Merlot. `KeyError`, and the loop crashes. You saw
          this one live.
        - **`'pinot noir'` and `'  Pinot Noir  '`**: the same wine with different casing or spacing.
          `KeyError` again. You probably will not see this one live, because Claude tends to tidy the
          input into `"Pinot Noir"` before calling the tool. That is exactly why the handler must not
          depend on it: other prompts, other models, and other callers will not always tidy for you.
        - **`'Riesling'`**: no error at all, which makes it the most dangerous of the three. It returns
          the Winter Heron Cellars bottle with quantity 0, so Claude would happily offer you a wine you
          already finished.

        Here is what the offline checker makes of the starter handler. It makes no API calls, so it
        gives the same answer every time.
    """),
    code("lab_checks.check_handler(check_cellar)"),
    md("""
        ### Design decisions for the fix

        - **Normalize, then match the whole name.** Casing and surrounding spaces should not matter.
          But match the *whole* varietal: "Pinot Noir" should not return the Rosé of Pinot Noir. A
          substring match would return it, and a rosé is a different wine. Accents are not folded
          either, so "rose of pinot noir" does not match "Rosé of Pinot Noir". Is that the right call?
          It is one of the discussion questions at the end.
        - **An empty result is not an error.** Riesling is a real varietal in this cellar; you have
          just run out. The question has a true answer, "none right now", so the tool returns an empty
          list of bottles.
        - **Invalid input is an error, with a useful message.** Merlot was never in the cellar. The
          tool raises `ValueError` with a message listing the varietals in stock, so Claude can suggest
          one. Out-of-stock varietals stay off that list, or Claude might suggest a wine you cannot open.
        - **Return only what Claude needs:** vineyard, vintage, region, tasting notes, quantity, and
          drink-by year.
    """),
    exercise(
        FIXED_HANDLER_SOLUTION,
        '''
            def check_cellar(varietal: str) -> dict:
                """Look up the in-stock bottles in the cellar for one varietal.

                :param varietal: The grape varietal Claude asked about, in any casing or spacing.
                :returns: ``{"varietal": ..., "bottles": [...]}`` with in-stock bottles only.
                :raises ValueError: If the cellar has never held this varietal.
                """
                # TODO: rewrite this function so that:
                #   1. Input that differs only in letter case or surrounding spaces still matches.
                #   2. Only the whole varietal name matches ("Pinot Noir" does not return the rosé).
                #   3. Bottles with quantity 0 are left out.
                #   4. Each bottle has only vineyard, vintage, region, tasting_notes, quantity, drink_by.
                #   5. A varietal the cellar has held, with none in stock, returns an empty "bottles" list.
                #   6. A varietal the cellar has never held raises ValueError naming the varietals in stock.
                return {"varietal": varietal, "bottles": CELLAR_BY_VARIETAL[varietal]}
        ''',
        "fixed-handler",
    ),
    _hint_cell(
        _details(
            "Hint 1: matching regardless of case and spaces",
            "Put both sides in the same standard form, then compare with `==`:\n\n"
            "```python\n"
            "def normalize(varietal: str) -> str:\n"
            "    return varietal.strip().casefold()\n"
            "```\n\n"
            "`.strip()` removes surrounding spaces. `.casefold()` is like `.lower()`, but built for "
            "comparing text, so it also handles letters such as the German ß. Comparing whole "
            "normalized names with `==` keeps the rosé out; `in` would let it in.",
        ),
        _details(
            "Hint 2: empty result versus ValueError",
            "Work in two steps. First collect every bottle whose normalized varietal matches, ignoring "
            "quantity. If that list is empty, the cellar has never held the varietal, so raise:\n\n"
            "```python\n"
            'in_stock = sorted({b["varietal"] for b in CELLAR if b["quantity"] > 0})\n'
            "raise ValueError(f\"The cellar has never held {varietal.strip()!r}. \"\n"
            "                 f\"Varietals in stock: {', '.join(in_stock)}.\")\n"
            "```\n\n"
            "If the list is not empty, leave out the bottles with `quantity == 0`. An empty list after "
            "that is a valid answer, not an error.",
        ),
        _details(
            "Hint 3: keeping only the fields Claude needs",
            "```python\n"
            'RESULT_FIELDS = ("vineyard", "vintage", "region", "tasting_notes", "quantity", "drink_by")\n'
            "summary = {name: bottle[name] for name in RESULT_FIELDS}\n"
            "```",
        ),
        _details("Hint 4: the full handler", _in_hint(FIXED_HANDLER_SOLUTION)),
    ),
    md("""
        ### Checkpoint: the handler

        Run this after each change. It reports every case, with a hint for the ones that still fail.
    """),
    checkpoint("lab_checks.check_handler(check_cellar)"),
    md("""
        ### Fix the dispatch function

        The handler now raises `ValueError` for bad input. Something still has to catch that, or the
        loop still crashes. That is the dispatch function's job: turn a failure into a `tool_result`
        that tells Claude what went wrong. The API has a flag for exactly this, `"is_error": True`.
        Claude reads the error message and answers the user, instead of your program dying.

        Notice that only `ValueError` is caught. It means "the input was bad, tell Claude." Any other
        exception is a real bug in your code, and hiding it from you would make it harder to find.
    """),
    exercise(
        TOOL_ERROR_AND_DISPATCH_SOLUTION,
        '''
            def dispatch_tool(tool_use: ToolUseBlock) -> dict:
                """Run the tool Claude asked for and wrap its output as a ``tool_result`` block.

                :param tool_use: A ``tool_use`` block from ``response.content``.
                :returns: A ``tool_result`` block. If the tool failed, it has ``"is_error": True``.
                """
                # TODO: keep the conversation alive when a tool fails.
                #   1. Wrap the check_cellar call in try/except ValueError.
                #   2. On ValueError, return {"type": "tool_result", "tool_use_id": tool_use.id,
                #      "content": str(error), "is_error": True}.
                #   3. For an unknown tool name, return the same kind of error result instead of raising.
                if tool_use.name == "check_cellar":
                    result = check_cellar(tool_use.input["varietal"])
                else:
                    raise ValueError(f"Unknown tool: {tool_use.name}")

                return {
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": json.dumps(result),
                }
        ''',
        "fixed-dispatch",
    ),
    _hint_cell(
        _details("Hint: the full dispatch function", _in_hint(TOOL_ERROR_AND_DISPATCH_SOLUTION)),
    ),
    md("""
        ### Re-run the conversation

        Same question as before. This time the tool reports an error, and Claude recovers.
    """),
    code("""
        merlot_messages = run_conversation("Do I have any Merlot?")
        show_conversation(merlot_messages)
    """),
    checkpoint("lab_checks.check_part4(merlot_messages)"),
    md("""
        The fixed handler also takes care of casing, whether or not Claude tidies the input first:
    """),
    code("""
        pinot_messages = run_conversation("Anything pinot noir in there?")
        show_conversation(pinot_messages)
    """),
    checkpoint("lab_checks.check_part3(pinot_messages)"),
    # ----- Stretch ----------------------------------------------------------
    md("""
        ## Stretch (optional): a second tool and a sommelier

        **What you will do:** add `bottles_to_drink_soon`, a tool that finds bottles near or past their
        drink-by year, then give Claude a system prompt that makes it a sommelier.

        **Why it matters:** real apps have several tools, and Claude chooses between them using their
        descriptions. The year is a parameter rather than a reading of the system clock, so the answer
        is the same every time you run the lab.

        **Success looks like:** Claude picks the right tool on its own, and `check_part3` passes for
        both conversations.

        These cells replace `dispatch_tool` and `ask_claude`. If you go back to an earlier part, run
        its cells again first.
    """),
    exercise(
        DRINK_SOON_HANDLER_SOLUTION,
        '''
            def bottles_to_drink_soon(year: int, within_years: int = 1) -> dict:
                """Find in-stock bottles that should be opened by ``year + within_years``.

                :param year: The current year, as the user states it.
                :param within_years: How many years ahead to look.
                :returns: ``{"year": ..., "within_years": ..., "bottles": [...]}``, soonest first.
                """
                # TODO: return the in-stock bottles whose drink_by is no later than
                # year + within_years (including any already past it), soonest first.
                # Give each bottle its varietal, vineyard, vintage, quantity, and drink_by.
                return {"year": year, "within_years": within_years, "bottles": []}
        ''',
        "drink-soon-handler",
    ),
    _hint_cell(
        _details("Hint: the full handler", _in_hint(DRINK_SOON_HANDLER_SOLUTION)),
    ),
    code("""
        for bottle in bottles_to_drink_soon(2026)["bottles"]:
            print(bottle["drink_by"], bottle["vintage"], bottle["vineyard"], bottle["varietal"])
    """),
    exercise(
        DRINK_SOON_TOOL_SOLUTION,
        '''
            # TODO: write the definition for the second tool. Its input_schema needs a required
            # integer "year" and an optional integer "within_years". In the description, say
            # that Claude must use the year the user gives, and ask if there is none.
            DRINK_SOON_TOOL: dict = {
                "name": "bottles_to_drink_soon",
                "description": "",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            }
        ''',
    ),
    _hint_cell(
        _details("Hint: the full definition", _in_hint(DRINK_SOON_TOOL_SOLUTION)),
    ),
    exercise(
        STRETCH_DISPATCH_SOLUTION,
        '''
            def dispatch_tool(tool_use: ToolUseBlock) -> dict:
                """Run whichever of the two tools Claude asked for, as a ``tool_result`` block.

                :param tool_use: A ``tool_use`` block from ``response.content``.
                :returns: A ``tool_result`` block. If the tool failed, it has ``"is_error": True``.
                """
                # TODO: copy your Part 4 dispatch_tool logic here, and add a branch for
                # "bottles_to_drink_soon". Read the year with tool_use.input["year"], and
                # within_years with tool_use.input.get("within_years", 1), because Claude
                # may leave out an optional argument.
                return {
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": "This tool is not implemented yet.",
                    "is_error": True,
                }
        ''',
        "stretch-dispatch",
    ),
    _hint_cell(
        _details("Hint: the full dispatch function", _in_hint(STRETCH_DISPATCH_SOLUTION)),
    ),
    exercise(
        SOMMELIER_SOLUTION,
        '''
            # TODO: write a system prompt that makes Claude a sommelier who uses the tools,
            # never suggests a bottle the tools did not return, and always names the vintage,
            # vineyard, and varietal. Then pass it to the API with system=SOMMELIER_PROMPT.
            SOMMELIER_PROMPT: str = ""


            def ask_claude(messages: list[dict]) -> Message:
                """Send the conversation so far to Claude, with the tools and the sommelier prompt.

                :param messages: The conversation history, oldest message first.
                :returns: Claude's response.
                """
                return client.messages.create(
                    model=MODEL,
                    max_tokens=1024,
                    tools=TOOLS,
                    messages=messages,
                )
        ''',
    ),
    _hint_cell(
        _details("Hint: the full prompt and ask_claude", _in_hint(SOMMELIER_SOLUTION)),
    ),
    code("""
        TOOLS = [CHECK_CELLAR_TOOL, DRINK_SOON_TOOL]

        drink_messages = run_conversation("It is 2026. Which bottles should I open within the next year?")
        show_conversation(drink_messages)
    """),
    checkpoint("lab_checks.check_part3(drink_messages)"),
    code("""
        risotto_messages = run_conversation("I'm making mushroom risotto tonight. Any Pinot Noir that would work?")
        show_conversation(risotto_messages)
    """),
    checkpoint("lab_checks.check_part3(risotto_messages)"),
    # ----- Wrap-up ----------------------------------------------------------
    md("""
        ## Where to go next

        You called the Messages API, defined a tool, wrote the loop that runs it, and made the tool
        fail gracefully. Some questions to think about, or to discuss with your group:

        - Should a bottle with quantity 0 count as "in the cellar"?
        - Should "Pinot" match "Rosé of Pinot Noir"? Should "rose" match "Rosé"?
        - What should a tool return when the input is valid but there are no results, compared with
          when the input is invalid?

        To keep going, read the Claude documentation on tool use: <https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview>
    """),
]


def build(variant: str) -> NotebookNode:
    """Assemble one notebook from ``CELLS``.

    :param variant: ``"solution"`` or ``"lab"``.
    :returns: A notebook with outputs cleared and stable cell ids.
    :raises ValueError: If ``variant`` is not a known notebook.
    """
    if variant not in VARIANTS:
        raise ValueError(f"Unknown notebook variant {variant!r}; expected one of {VARIANTS}.")

    notebook = nbformat.v4.new_notebook()
    notebook.metadata = {
        "kernelspec": {"display_name": "Python 3 (ipykernel)", "language": "python", "name": "python3"},
        "language_info": {"name": "python"},
    }

    for cell in CELLS:
        source = cell.solution if variant == "solution" else cell.lab
        if source is None:
            continue

        tags = list(cell.tags)
        if variant == "lab" and cell.kind == "code" and "# TODO" in source:
            tags.append("todo")

        if cell.kind == "markdown":
            node = nbformat.v4.new_markdown_cell(source)
        else:
            node = nbformat.v4.new_code_cell(source)
        node.id = f"cell-{len(notebook.cells) + 1:02d}"
        if tags:
            node.metadata["tags"] = tags
        notebook.cells.append(node)

    nbformat.validate(notebook)
    return notebook


def main() -> None:
    """Write both notebooks next to ``cellar.json``.

    :returns: Nothing. Prints the paths it wrote.
    """
    for variant in VARIANTS:
        path = OUTPUT_PATHS[variant]
        path.write_text(nbformat.writes(build(variant)) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
