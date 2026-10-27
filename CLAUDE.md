# CLAUDE.md: Claude Tool-Use Lab ("Give Claude a Tool")

## What this project is

A short, hands-on Jupyter lab that teaches a developer to make their first Claude API call and then give Claude a tool. It is a teaching artifact first and a code sample second. Every decision should make the learner's path clearer, not make the code cleverer.

**Learner outcome:** by the end, the learner can (1) call the Claude Messages API and read the structured response, (2) define a tool with a JSON schema, (3) write the loop that executes a tool and returns the result to Claude, and (4) debug a tool handler that fails on realistic model input, returning a clear error instead of crashing.

**Target learner:** a developer comfortable with basic Python who has never used the Claude API. Total time: about 45 minutes, plus an optional stretch.

**Theme:** a personal wine cellar. Data lives in `cellar.json` (12 bottles, fictional vineyards). Everything except the Claude API call itself is local and deterministic.

## Tech constraints

- Python 3.12+.
- Use `uv` for everything: `uv init`, `uv add`, `uv run`. Do not use pip, and do not create a `requirements.txt`. Dependencies live in `pyproject.toml` with a committed `uv.lock`.
- Runtime dependencies: `anthropic`, `python-dotenv`. Dev dependencies (`uv add --dev`): `jupyterlab`, `ipykernel`, `pytest`, `nbformat`.
- The API key comes from the `ANTHROPIC_API_KEY` environment variable, loaded from a `.env` file via `python-dotenv`. Commit `.env.example`, never `.env`. Add `.env` to `.gitignore`.
- The model is a single constant near the top of each notebook, overridable by environment variable: `MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-5-5")`. Before finalizing, confirm the default model ID against the current Anthropic docs. Use a small, inexpensive model so the lab costs pennies to run.
- The author develops on Windows with PowerShell. Every setup and run command in the README must work in PowerShell; show bash equivalents where they differ (for example, setting environment variables).

## Code style

- Type hints on every function signature and on module-level constants where helpful.
- Sphinx-style docstrings (`:param name:`, `:returns:`, `:raises:`) on every function, including the small ones in notebooks. Learners copy what they see, so model good habits.
- Prefer clarity over brevity in learner-facing code. No one-liners that hide a concept.
- American English in all prose and comments.
- Do not use em-dashes in any prose, comments, or Markdown cells.

## Repository layout

```
claude-tool-lab/
├── README.md                  # learner-facing: outcome, prerequisites, setup, how to run, troubleshooting
├── CLAUDE.md                  # this file
├── pyproject.toml
├── uv.lock
├── .env.example               # ANTHROPIC_API_KEY=your-key-here, CLAUDE_MODEL= (optional)
├── .gitignore
├── cellar.json                # provided; do not change the data without asking
├── lab_checks.py              # checkpoint functions the notebooks call
├── lab.ipynb                  # learner version with TODO cells and the planted bug
├── solution.ipynb             # complete reference solution
├── docs/
│   └── instructor-notes.md    # design decisions, expected stumbling points, timing, discussion prompts
└── tests/
    └── test_lab_checks.py     # proves the checks catch the bug and pass the fix
```

## Lab structure (both notebooks follow these parts and headings)

Each part opens with a short Markdown cell: what you will do, why it matters, and what success looks like. Each part ends with a checkpoint cell that calls a function from `lab_checks.py` and prints a clear pass message or a specific hint.

### Part 0: Setup (about 5 minutes)

- Load `.env`, read `ANTHROPIC_API_KEY`, and create the client.
- Checkpoint: `check_setup()` confirms the key is present and the `anthropic` package imports. On failure, it prints a friendly message that names the likely cause (missing `.env`, key not set in this shell, wrong kernel) instead of a stack trace. The point is to separate environment problems from conceptual ones.
- Load `cellar.json` and show a small, readable table of the bottles.

### Part 1: Hello, Claude (about 5 minutes)

- One `client.messages.create` call with a simple user message.
- Print the whole response object, then walk through it: content blocks, `stop_reason`, and `usage`.
- Teaching point: the response is structured data, not a string.
- Checkpoint: `check_part1(response)` verifies `stop_reason == "end_turn"` and that the first content block is text.

### Part 2: Give Claude a tool (about 10 minutes)

- Define the `check_cellar` tool: name, description, and an `input_schema` with one required string property, `varietal`. Write the description well, and add a Markdown cell explaining that the description is how Claude decides when to use the tool.
- Send "Do I have any Pinot Noir?" with the tool attached.
- Inspect the response: `stop_reason == "tool_use"`, the `tool_use` block, its `id`, `name`, and `input`.
- Teaching point: Claude does not run the tool. Your code does.
- Checkpoint: `check_part2(response)` verifies a `tool_use` block for `check_cellar` with a `varietal` string in its input.

### Part 3: Close the loop (about 15 minutes, the main exercise)

- Provide the starter tool handler (see "The planted bug" below).
- The learner writes `run_conversation(user_message: str, max_turns: int = 5) -> list[dict]`, which:
  1. Sends the message with tools attached.
  2. While `stop_reason == "tool_use"`: runs each requested tool through a dispatch function, appends the assistant turn and a user turn containing `tool_result` blocks (matching `tool_use_id`), and calls the API again.
  3. Stops on `end_turn` or when `max_turns` is reached, and returns the full message history.
- In `lab.ipynb`, the loop body is a TODO with numbered hints in comments. In `solution.ipynb`, it is complete.
- Checkpoint: `check_part3(messages)` checks invariants, never exact wording: the tool was called at least once, every `tool_use` has a matching `tool_result`, the final turn ended with `end_turn`, and the final text mentions at least one bottle that actually exists in the cellar (by vineyard name or vintage).

### Part 4: When the model surprises you (about 10 minutes)

- The learner asks "Anything pinot noir in there?" or "Do I have any Merlot?" and watches the starter handler fail.
- Guide them to reproduce the failure directly (call the handler with the bad input, no API needed), read the traceback, and fix it.
- Checkpoint: `check_handler(check_cellar)` runs the handler against a fixed set of offline inputs and reports each case as pass or fail with a hint. This check makes no API calls, so it is fully deterministic.
- Then re-run the Part 3 conversation to show Claude recovering gracefully when the tool returns an error.

### Stretch (optional)

- Add a second tool, `bottles_to_drink_soon(year: int, within_years: int = 1)`, using `drink_by`. The year is a parameter (never the system clock) so results stay deterministic.
- Add a system prompt that makes Claude act as a sommelier who always names the vineyard and vintage.

## The planted bug (lab.ipynb only)

The starter handler indexes bottles by exact varietal string:

```python
CELLAR_BY_VARIETAL: dict[str, list[dict]] = {}
for bottle in CELLAR:
    CELLAR_BY_VARIETAL.setdefault(bottle["varietal"], []).append(bottle)

def check_cellar(varietal: str) -> list[dict]:
    return CELLAR_BY_VARIETAL[varietal]
```

It works for `"Pinot Noir"` and fails in three realistic ways:

1. `"pinot noir"` or `" Pinot Noir "` raises `KeyError` (case and whitespace).
2. `"Merlot"` raises `KeyError` (not in the cellar), and the exception crashes the conversation loop.
3. `"Riesling"` returns a bottle with `quantity: 0` as if it were available.

The bug must be honest, not contrived: write the starter the way a reasonable developer would on a first pass. Do not add comments that point at the bug.

## The reference fix (solution.ipynb)

- Normalize input with `.strip().casefold()` and match against the normalized varietal. Use **exact normalized matching, not substring matching**, so "Pinot Noir" does not also return the "Rosé of Pinot Noir" or "Gamay Noir". Note this choice in a Markdown cell, because it is a good discussion point.
- Exclude bottles with `quantity == 0` from results.
- Return a dict, not a bare list: `{"varietal": ..., "bottles": [...]}` with only the fields Claude needs (vineyard, vintage, region, tasting_notes, quantity, drink_by).
- For an unknown varietal, raise `ValueError` with a message that lists the varietals actually available.
- In the dispatch function, catch `ValueError` (and unknown tool names) and return a `tool_result` with `is_error: True` and the message as content, so Claude can recover and answer the user instead of the program crashing.

## lab_checks.py

- Pure functions with type hints and Sphinx docstrings: `check_setup`, `check_part1`, `check_part2`, `check_part3`, `check_handler`.
- Each prints `PASS: ...` or `NOT YET: ...` with a specific, actionable hint. No emoji. Return a `bool` as well so tests can use it.
- `check_handler` test cases, at minimum: `"Pinot Noir"` (3 bottles: B001, B002, B009), `"pinot noir"`, `"  Pinot Noir  "`, `"Riesling"` (raises `ValueError` or returns no bottles, so it must not report B008 as available; pick one behavior and make the check and solution agree), `"Merlot"` (raises `ValueError` whose message names available varietals), and `"Pinot Noir"` must not include B011 or B012.

## tests/test_lab_checks.py

- Contains a copy of the buggy starter handler and the reference handler (small duplication is fine here).
- Asserts that `check_handler` **fails** the buggy version and **passes** the reference version.
- Asserts that `check_part3` passes a hand-built, valid message history and fails histories with a missing `tool_result`, a wrong `tool_use_id`, or a hallucinated bottle.
- No test may call the real API. Run with `uv run pytest`.

## Notebook hygiene

- Create and edit notebooks with `nbformat` (a small build script is fine) so they are always valid JSON.
- Commit both notebooks with outputs cleared, so no keys or long outputs end up in git.
- Ask before running any cell that calls the live API. Offline cells and `uv run pytest` can be run freely.

## README.md (learner-facing)

Sections, in order: what you will build (one paragraph and the four outcomes), prerequisites (Python 3.12+, `uv`, an Anthropic API key, approximate cost), setup (clone, `uv sync`, copy `.env.example` to `.env`, PowerShell and bash variants), run (`uv run jupyter lab`, open `lab.ipynb`), how the checkpoints work, troubleshooting (key not found, wrong kernel, authentication error, rate limit, model not found), and where to go next.

## docs/instructor-notes.md

Short and practical: learning objectives, timing per part, where learners are expected to stall and the hint for each, why the bug was designed this way, why checks test invariants instead of exact model text, and three discussion prompts (for example: should a bottle with quantity 0 count as "in the cellar"? Should "Pinot" match "Rosé of Pinot Noir"? What should a tool return when the input is valid but there are no results?).

## Git

- Small, meaningful commits as you go (scaffold, data and checks, notebooks, docs).
- Commit messages describe the change plainly. Never add `Co-Authored-By`, `Claude-Session`, "Generated with Claude Code", or any other AI attribution lines to commit messages or PR descriptions.

## Definition of done

- `uv sync` then `uv run pytest` passes from a fresh clone.
- `lab.ipynb` runs top to bottom with a valid key, showing the Part 4 failure where intended.
- `solution.ipynb` runs top to bottom with every checkpoint passing.
- README setup works in PowerShell exactly as written.