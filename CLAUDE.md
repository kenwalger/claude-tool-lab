# CLAUDE.md: Claude Tool-Use Lab ("Give Claude a Tool")

## What this project is

A short, hands-on Jupyter lab that teaches a developer to make their first Claude API call and then give Claude a tool. It is a teaching artifact first and a code sample second. Every decision should make the learner's path clearer, not make the code cleverer.

**Learner outcome:** by the end, the learner can (1) call the Claude Messages API and read the structured response, (2) define a tool with a JSON schema, (3) write the loop that executes a tool and returns the result to Claude, and (4) debug a tool handler that fails on realistic model input, returning a clear error instead of crashing.

**Target learner:** a developer comfortable with basic Python who has never used the Claude API. Total time: about 45 minutes, plus an optional stretch.

**Theme:** a personal wine cellar. Data lives in `cellar.json` (12 bottles, fictional vineyards). Everything except the Claude API call itself is local and deterministic.

## Tech constraints

- Python 3.12+ (`requires-python = ">=3.12"`).
- Use `uv` for everything: `uv init`, `uv add`, `uv run`. Do not use pip, and do not create a `requirements.txt`. Dependencies live in `pyproject.toml` with a committed `uv.lock`.
- Runtime dependencies: `anthropic`, `python-dotenv`. Dev dependencies (`uv add --dev`): `jupyterlab`, `ipykernel`, `pytest`, `nbformat`.
- The API key comes from the `ANTHROPIC_API_KEY` environment variable, loaded from a `.env` file via `python-dotenv`. Commit `.env.example`, never `.env`.
- The model is a single constant near the top of each notebook, overridable by environment variable: `MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-5-5")`. Verified against the current Anthropic docs on 2026-10-27.
- Set `max_tokens` to 1024 or higher. Adaptive thinking is on by default for this model and thinking tokens count toward the limit, so a low cap can end a turn on `max_tokens`.
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
├── .gitignore                 # already ignores .env, .venv, and commit-message.txt
├── cellar.json                # provided; do not change the data without asking
├── lab_checks.py              # checkpoint functions the notebooks call
├── lab.ipynb                  # learner version with TODO cells and the planted bug
├── solution.ipynb             # complete reference solution
├── scripts/
│   └── build_notebooks.py     # generates both notebooks from one set of cell sources
├── docs/
│   └── instructor-notes.md    # design decisions, expected stumbling points, timing, discussion prompts
└── tests/
    ├── test_lab_checks.py     # proves the checks catch the bug and pass the fix
    └── test_notebooks.py      # both notebooks are valid and have no outputs
```

Leave `prompt.md` and `commit-message.txt` alone except as described under "Git workflow."

## Lab structure (both notebooks follow these parts and headings)

Each part opens with a short Markdown cell: what you will do, why it matters, and what success looks like. Each part ends with a checkpoint cell that calls a function from `lab_checks.py` and prints a clear pass message or a specific hint.

### Part 0: Setup (about 5 minutes)

- Load `.env`, read `ANTHROPIC_API_KEY`, and create the client.
- Checkpoint: `check_setup()` confirms the key is present, the `anthropic` package imports, and the kernel is the project's environment (`sys.prefix` points at the project `.venv`). On failure, it prints a friendly message that names the likely cause (missing `.env`, key not set in this shell, wrong kernel) instead of a stack trace. The point is to separate environment problems from conceptual ones.
- Load `cellar.json` and show a small, readable table of the bottles.

### Part 1: Hello, Claude (about 5 minutes)

- One `client.messages.create` call with a simple user message.
- Print the whole response object, then walk through it: content blocks, `stop_reason`, and `usage`.
- Explain the thinking block that may appear first (it can come back empty except for a signature), and why code must select content blocks **by type, never by position**.
- In the stop-reasons walkthrough, mention `end_turn`, `tool_use`, `max_tokens`, and `refusal`.
- Teaching point: the response is structured data, not a string.
- Checkpoint: `check_part1(response)` verifies `stop_reason == "end_turn"` and that the content **contains** a text block.

### Part 2: Give Claude a tool (about 10 minutes)

- Define the `check_cellar` tool: name, description, and an `input_schema` with one required string property, `varietal`. Write the description well, and add a Markdown cell explaining that the description is how Claude decides when to use the tool.
- Send "Do I have any Pinot Noir?" with the tool attached.
- Inspect the response: `stop_reason == "tool_use"`, the `tool_use` block, its `id`, `name`, and `input`.
- Teaching point: Claude does not run the tool. Your code does.
- Checkpoint: `check_part2(response)` verifies a `tool_use` block for `check_cellar` with a `varietal` string in its input.

### Part 3: Close the loop (about 15 minutes, the main exercise)

- Provide the starter tool handler and a starter dispatch function (see "The planted bug" below).
- The learner writes `run_conversation(user_message: str, max_turns: int = 5) -> list[dict]`, which:
  1. Sends the message with tools attached.
  2. While `stop_reason == "tool_use"`: appends the assistant turn **as `response.content`, exactly as returned** (thinking blocks must go back unchanged), runs each requested tool through the dispatch function, appends a user turn containing `tool_result` blocks (matching `tool_use_id`), and calls the API again.
  3. Stops on `end_turn` or when `max_turns` is reached, appends the final assistant turn, and returns the full message history.
- Because assistant content is returned as-is, message `content` values may be SDK objects rather than plain dicts. The checks must accept both.
- The Part 3 hints must warn against the most likely learner mistake: rebuilding the assistant turn by hand as `{"role": "assistant", "content": text}`.
- In `lab.ipynb`, the loop body is a TODO with numbered hints in comments. In `solution.ipynb`, it is complete.
- Checkpoint: `check_part3(messages)` checks invariants, never exact wording:
  - the tool was called at least once;
  - every `tool_use` has a matching `tool_result`;
  - the conversation ended cleanly, inferred from the history: the last message is from the assistant, contains text, and contains no `tool_use` blocks;
  - the final text names at least one **vineyard that appeared in a `tool_result` in this conversation** (vineyard names, not vintages, since vintages repeat across bottles).

### Part 4: When the model surprises you (about 10 minutes)

- Lead with the failure that reliably happens live: ask "Do I have any Merlot?" The starter handler raises `KeyError`, and because the starter dispatch has no error handling, the conversation loop crashes.
- Then show the failures the model usually smooths over by calling the handler directly, no API needed: `"pinot noir"`, `"  Pinot Noir  "`, and `"Riesling"` (which returns an empty bottle as if it were available). Add a Markdown cell explaining honestly that Claude tends to normalize casing before calling the tool, which is exactly why the handler must not rely on it.
- The learner fixes both the handler and the dispatch function (see "The reference fix").
- Checkpoint: `check_handler(check_cellar)` runs the handler against a fixed set of offline inputs and reports each case as pass or fail with a hint. No API calls; fully deterministic.
- Re-run the Merlot conversation. Light checkpoint: the loop finishes, the `tool_result` has `is_error` set, and the conversation ends cleanly. (`check_part3` is not used here, because no real bottle is named in a Merlot conversation.)

### Stretch (optional)

- Add a second tool, `bottles_to_drink_soon(year: int, within_years: int = 1)`, using `drink_by`. The year is a parameter (never the system clock) so results stay deterministic.
- Add a system prompt that makes Claude act as a sommelier who always names the vineyard and vintage.
- TODO cells in `lab.ipynb`; complete in `solution.ipynb`.

## The planted bug (lab.ipynb only)

The starter handler indexes bottles by exact varietal string, and the starter dispatch calls it with no error handling:

```python
CELLAR_BY_VARIETAL: dict[str, list[dict]] = {}
for bottle in CELLAR:
    CELLAR_BY_VARIETAL.setdefault(bottle["varietal"], []).append(bottle)

def check_cellar(varietal: str) -> list[dict]:
    return CELLAR_BY_VARIETAL[varietal]
```

It works for `"Pinot Noir"` and fails in three realistic ways:

1. `"Merlot"` raises `KeyError` (never in the cellar), and the exception crashes the conversation loop.
2. `"pinot noir"` or `" Pinot Noir "` raises `KeyError` (case and whitespace).
3. `"Riesling"` returns a bottle with `quantity: 0` as if it were available.

The bug must be honest, not contrived: write the starter the way a reasonable developer would on a first pass. Do not add comments that point at the bug.

## The reference fix (solution.ipynb)

- Normalize input with `.strip().casefold()` and match against the normalized varietal. Use **exact normalized matching, not substring matching**, so "Pinot Noir" does not also return the "Rosé of Pinot Noir" or "Gamay Noir". Note this choice in a Markdown cell, because it is a good discussion point. Accent folding is out of scope ("rose of pinot noir" will not match "Rosé of Pinot Noir"); that is a discussion prompt too.
- Exclude bottles with `quantity == 0` from results.
- Return a dict, not a bare list: `{"varietal": ..., "bottles": [...]}` with only the fields Claude needs (vineyard, vintage, region, tasting_notes, quantity, drink_by).
- **Valid input, no results:** a varietal the cellar has held but has none in stock (Riesling) returns `{"varietal": "Riesling", "bottles": []}`. This is not an error.
- **Invalid input:** a varietal the cellar has never held (Merlot) raises `ValueError` with a message listing the varietals currently **in stock** (so the message does not steer Claude toward Riesling).
- In the dispatch function, catch `ValueError` (and unknown tool names) and return a `tool_result` with `is_error: True` and the message as content, so Claude can recover and answer the user instead of the program crashing.

## lab_checks.py

- Pure functions with type hints and Sphinx docstrings: `check_setup`, `check_part1`, `check_part2`, `check_part3`, `check_handler`, plus a light check for the Part 4 re-run.
- Each prints `PASS: ...` or `NOT YET: ...` with a specific, actionable hint. No emoji. Return a `bool` as well so tests can use it.
- Accept message content as plain dicts or SDK objects.
- `check_handler` test cases, at minimum:
  - `"Pinot Noir"` returns exactly B001, B002, and B009, and not B011 or B012;
  - `"pinot noir"` and `"  Pinot Noir  "` return the same three;
  - `"Riesling"` returns an empty `bottles` list (B008 must not appear);
  - `"Merlot"` raises `ValueError` whose message names in-stock varietals and does not name Riesling.

## tests

- `tests/test_lab_checks.py` contains a copy of the buggy starter handler and the reference handler (small duplication is fine here). It asserts that `check_handler` **fails** the buggy version and **passes** the reference version, and that `check_part3` passes a hand-built valid history and fails histories with a missing `tool_result`, a wrong `tool_use_id`, an unfinished final turn, or a vineyard that never appeared in a `tool_result`.
- `tests/test_notebooks.py` asserts both notebooks are valid and committed with no outputs.
- No test may call the real API. Run with `uv run pytest`.

## Notebook hygiene

- Generate both notebooks with `scripts/build_notebooks.py` (using `nbformat`) from one set of cell sources: `solution.ipynb` first, then `lab.ipynb` with the TODOs and planted bug swapped in. Edit the build script, not the notebooks, and regenerate.
- Commit both notebooks with outputs cleared, so no keys or long outputs end up in git.
- Ask before running any cell that calls the live API. Offline cells and `uv run pytest` can be run freely.

## README.md (learner-facing)

Sections, in order: what you will build (one paragraph and the four outcomes), prerequisites (Python 3.12+, `uv`, an Anthropic API key, approximate cost), setup (clone, `uv sync`, copy `.env.example` to `.env`, PowerShell and bash variants), run (`uv run jupyter lab`, open `lab.ipynb`), how the checkpoints work, troubleshooting (key not found, wrong kernel, authentication error, rate limit, model not found, turn ended on `max_tokens`), and where to go next.

## docs/instructor-notes.md

Short and practical: learning objectives, timing per part, where learners are expected to stall and the hint for each, why the bug was designed this way (including why the casing failure is shown offline rather than live), why checks test invariants instead of exact model text, the known limit of the vineyard check (it cannot catch an invented bottle mentioned alongside a real one), and discussion prompts:

- Should a bottle with quantity 0 count as "in the cellar"?
- Should "Pinot" match "Rosé of Pinot Noir"? Should "rose" match "Rosé"?
- What should a tool return when the input is valid but there are no results, versus when the input is invalid?

## Git workflow

**Do not run `git add`, `git commit`, or `git push`.** The author handles all commits and pushes.

At the end of each build stage:

1. Overwrite `commit-message.txt` (it is gitignored) with the commit message for that stage: a subject line of 72 characters or fewer in the imperative mood, a blank line, then a short body describing what changed and why.
2. In your chat response, list the files that belong in that commit.
3. Stop and wait for the author to confirm the commit before starting the next stage.

Commit messages describe the change plainly. Never add `Co-Authored-By`, `Claude-Session`, "Generated with Claude Code", or any other AI attribution lines.

## Definition of done

- `uv sync` then `uv run pytest` passes from a fresh clone.
- `lab.ipynb` runs top to bottom with a valid key, showing the Part 4 failure where intended.
- `solution.ipynb` runs top to bottom with every checkpoint passing.
- README setup works in PowerShell exactly as written.