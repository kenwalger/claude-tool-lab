# Starting prompt for Claude Code

Paste the text below into Claude Code from the root of an empty `claude-tool-lab` folder that already contains `CLAUDE.md` and `cellar.json`.

---

Read `CLAUDE.md` and `cellar.json` in this folder. We're building the Claude tool-use lab described in `CLAUDE.md`.

Before writing any code, give me a short plan:

1. The build order you'll follow.
2. Anything in `CLAUDE.md` that's ambiguous or that you'd push back on, especially the planted bug, the check design, and the Riesling (quantity 0) behavior.
3. The default model ID you'll use, and confirmation that you checked it against the current Anthropic docs.

Wait for my go-ahead after the plan.

Once I approve, build it in stages, committing after each one:

1. Scaffold with `uv` (Python 3.12+), `.gitignore`, `.env.example`.
2. `lab_checks.py` and `tests/test_lab_checks.py`, then run `uv run pytest` and show me the results. The tests must prove the checks fail the buggy handler and pass the reference handler.
3. `solution.ipynb`, then `lab.ipynb` derived from it (TODOs and the planted bug).
4. `README.md` and `docs/instructor-notes.md`.

Rules: type hints and Sphinx-style docstrings everywhere, `uv` only (no pip, no requirements.txt), no em-dashes in any prose, and no AI attribution lines in commits. Ask before running any cell that calls the live API. I'll run those myself.

When you finish, summarize what you built, anything you deviated from in `CLAUDE.md` and why, and anything you think a learner will still trip over.