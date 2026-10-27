# Instructor notes

Short, practical notes for running the "Give Claude a Tool" lab. The learner-facing setup is in the [README](../README.md).

## Learning objectives

By the end, a learner can:

1. Call the Claude Messages API and read the structured response: content blocks selected by type, `stop_reason`, and `usage`.
2. Define a tool with a JSON schema, and explain that the description is how Claude decides when to call it.
3. Write the loop that runs a tool and returns the result to Claude: append `response.content` unchanged, answer every `tool_use` with a matching `tool_result` in the next user message, and stop on `end_turn` or `max_turns`.
4. Debug a tool handler that fails on realistic model input, so it returns a clear error (`is_error: True`) instead of crashing the conversation.

The target learner knows basic Python and has never used the Claude API.

## Timing

| Part | Time | Notes |
|---|---|---|
| 0: Setup | about 5 min | Longer for anyone without `uv` or a key. Ask people to install `uv` and create a key beforehand. |
| 1: Hello, Claude | about 5 min | Mostly reading. |
| 2: Give Claude a tool | about 10 min | First exercise: the tool definition. |
| 3: Close the loop | about 15 min | The main exercise. Most of the help you give goes here. |
| 4: When the model surprises you | about 10 min | The handler fix and the dispatch fix. |
| Total | about 45 min | |
| Stretch (optional) | 15 to 20 min | Second tool, stretch dispatch, and the sommelier prompt. |

## Where learners stall, and the hint for each

**Part 0: the key is not loaded.** Usually `.env` was not created, still says `your-key-here`, or was edited after `load_dotenv()` ran. `check_setup` names which one. Hint: fix `.env`, then restart the kernel, because `load_dotenv()` does not replace a key that is already set. If a learner has an old key in their shell environment, it wins over `.env`.

**Part 0: the wrong kernel.** The learner started Jupyter outside `uv run`, or their editor picked a global Python. Hint: close Jupyter and run `uv run jupyter lab` from the project folder.

**Part 1: `response.content[0].text`.** It works until a thinking block comes first. Hint: select blocks by type, `[b for b in response.content if b.type == "text"]`, never by position.

**Part 2: Claude answers without calling the tool.** The description is empty or vague. Hint: the description is the only thing Claude reads. Say what it looks up, what it returns, and when to use it.

**Part 3: rebuilding the assistant turn.** The most common mistake is `{"role": "assistant", "content": text}` in place of `response.content`. It drops the `tool_use` block the result answers, and the thinking blocks the model needs back. `check_part3` reports it as a `tool_result` with no matching `tool_use`. Hint: append `response.content` exactly as it came back.

**Part 3: one user message per tool result.** All the results for one assistant turn go in a single user message. Hint: collect them in a list, then append once.

**Part 3: forgetting the final turn.** The loop exits, but the last assistant message is never appended, so the history ends with tool results. Hint: append Claude's final turn after the loop, the same way as inside it.

**Part 4: substring matching.** `"pinot noir" in varietal.lower()` also returns the Rosé of Pinot Noir. `check_handler` lists it as an extra bottle. Hint: normalize both sides, then compare whole names with `==`.

**Part 4: Riesling as an error.** Some learners raise `ValueError` because no bottle is in stock. Hint: the cellar has held Riesling, so the question has a true answer, "none right now". That is an empty list. `ValueError` is for a varietal the cellar has never held.

**Part 4: catching everything in dispatch.** `except Exception` hides real bugs in the learner's own code. Hint: catch only `ValueError`, which means "bad input, tell Claude".

**Stretch: the deadline.** Using `<` instead of `<=` drops bottles due in the deadline year. Leaving out past-due bottles drops the most urgent one. Reading the year from the clock passes the two 2026 cases, which is why `check_drink_soon` also tests 2030. The hints name each of these.

**Stretch: forgetting `system=`.** The sommelier prompt is written but never passed to the API. `check_sommelier(ask_claude)` catches this offline, before the conversation runs. Hint: replace the TODO comment inside `client.messages.create(...)` with `system=SOMMELIER_PROMPT`.

### Found in pilots

**Pilot 1: placeholders left in place.** In every TODO with a placeholder body, the author wrote the logic above the placeholder and left it in place. The placeholders returned plausible values (an empty list, a "not implemented" result), so they failed quietly. The fix: every TODO stub body is only `raise NotImplementedError(...)`, and each checkpoint shares a cell with the function it checks, so redefining the function always re-runs the check.

**Pilot 2: TODO errors taken for intended failures.** Part 4 fails on purpose several times before its TODOs (the live Merlot crash, the direct handler calls, and the starter's 1 of 5). The author treated the TODOs' `NotImplementedError`s as more of the same, skipped the TODOs, and moved on. The fix makes the two kinds of failure impossible to confuse:

- A plain-text banner goes before every cell that fails on purpose: "EXPECTED TO FAIL: read the error, then move on."
- A banner goes before every learner cell: "YOUR TURN: replace the raise line with your code."
- Every stub's message starts with `YOUR TURN:` and ends with "This is not one of the expected failures."
- The Merlot crash cell re-raises `NotImplementedError` instead of catching it with the expected `KeyError`.
- Before the stretch, a gate runs `check_handler` and probes `dispatch_tool` offline with a fake Merlot request. If either is unfinished, it stops with "Finish Part 4 first: ..." naming what is missing.
- `lab_checks.summary()` is the last code cell. It lists every part with `PASS` or `NOT YET`, so no one finishes feeling done when they are not.

## Why the bug is designed this way

The starter handler is what a reasonable developer writes on a first pass: a dict keyed by the exact varietal string, and a dispatch function with no error handling. It already returns the right shape, so exact `"Pinot Noir"` works and learners start `check_handler` at 1 of 5. Nothing in the code points at the bug.

The one exact-key lookup fails in three realistic ways:

1. **`"Merlot"` raises `KeyError`**, and with no error handling, it crashes the whole conversation. This is the failure that reliably happens live, so Part 4 leads with it.
2. **`"pinot noir"` and `"  Pinot Noir  "` raise `KeyError`.** This is shown offline, by calling the handler directly, because it rarely happens live: Claude usually tidies the input into `"Pinot Noir"` before calling the tool. A live demo would usually work and teach the wrong lesson. The handler still must not rely on that tidying, because other prompts, models, and callers will not always do it.
3. **`"Riesling"` returns a bottle with quantity 0** as if it were available. No error at all, which makes it the most dangerous of the three.

The reference fix separates two cases that learners often merge: valid input with no results (Riesling returns an empty list) and invalid input (Merlot raises `ValueError` listing what is in stock). The `ValueError` message leaves out out-of-stock varietals, so Claude does not suggest a wine the user cannot open.

## Why the checks test invariants, not text

Claude phrases its answer differently on every run, and a check that compares wording would fail correct code. The conversation checks test what must be true for any correct run instead: the tool was called, every `tool_use` has a matching `tool_result` in the next user message, the conversation ended with Claude's text and no pending `tool_use`, and the final answer names a vineyard that came back in a `tool_result` in that conversation. Vineyard names are used, not vintages, because vintages repeat across bottles.

The handler checks are offline and exact, because the handler is ordinary deterministic code.

### Known limits

- **The vineyard check cannot catch an invented bottle mentioned alongside a real one.** If Claude names the real Crooked Lantern Vineyard and also invents a second bottle, the check passes. It proves the answer used the tool's data, not that it used only that data.
- **`summary()` remembers conversation checks only for the current kernel.** After a restart, those rows say `NOT YET` until the learner runs those cells again. The offline rows are re-run every time.

## Discussion prompts

- Should a bottle with quantity 0 count as "in the cellar"?
- Should "Pinot" match "Rosé of Pinot Noir"? Should "rose" match "Rosé"? (The fix does not fold accents, so "rose of pinot noir" does not match.)
- What should a tool return when the input is valid but there are no results, versus when the input is invalid?
- In a pilot run, Claude noticed that `within_years=1` in 2026 includes all of 2027, and flagged it as beyond a strict 12-month window. When does a tool's meaning differ from the user's, and who should resolve it, the tool or the model?

## Maintaining the lab

- Edit `scripts/build_notebooks.py`, never the notebooks, then regenerate both: `uv run python scripts/build_notebooks.py`.
- `uv run pytest` checks, without calling the API, that the notebooks match the build script and have no outputs. It also checks that every lab stub raises `NotImplementedError`, that the checks fail the planted bug and pass the reference fix, and that the banners, gate, and summary are in place.
