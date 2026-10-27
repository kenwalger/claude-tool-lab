# Give Claude a Tool: a wine cellar lab

A short, hands-on Jupyter lab. You make your first call to the Claude API, then give Claude a tool that looks up bottles in a small personal wine cellar. You write the loop that runs the tool for Claude and sends back the result, and then you fix a tool handler that breaks on the kind of input a real model sends it. Everything except the call to Claude runs locally on a 12-bottle `cellar.json`, so your results are repeatable.

It takes about 45 minutes, plus an optional stretch.

By the end, you will be able to:

1. Call the Claude Messages API and read the structured response.
2. Define a tool with a JSON schema.
3. Write the loop that runs a tool and returns the result to Claude.
4. Debug a tool handler that fails on realistic model input, so it returns a clear error instead of crashing.

## Prerequisites

- **Python 3.12 or newer.** If you do not have it, `uv sync` downloads it for you.
- **uv**, the Python package and project manager. Install it from <https://docs.astral.sh/uv/getting-started/installation/>:

  ```powershell
  # Windows (PowerShell)
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

  ```bash
  # macOS or Linux
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

- **An Anthropic API key**, which you can create in the Claude Console at <https://platform.claude.com>.
- **Basic Python.** You do not need any experience with the Claude API.

**Approximate cost:** the lab uses `claude-haiku-5-5`, which costs $0.10 per million input tokens and $0.50 per million output tokens (prices checked on 2026-10-27). A full run, stretch included, makes about 15 API calls and usually costs around one cent. Even with many re-runs, it should stay well under 10 cents.

## Setup

Clone the repository and install the dependencies. `uv sync` creates a `.venv` folder in the project with everything the lab needs.

```powershell
git clone https://github.com/kenwalger/claude-tool-lab.git
cd claude-tool-lab
uv sync
```

Copy the example environment file and put your key in it.

```powershell
# Windows (PowerShell)
Copy-Item .env.example .env
notepad .env
```

```bash
# macOS or Linux
cp .env.example .env
nano .env    # or any editor
```

In `.env`, replace `your-key-here` with your key:

```
ANTHROPIC_API_KEY=sk-ant-...
```

Never commit `.env`. It is already in `.gitignore`.

**Optional: try another model.** `.env` also has a commented-out line, `# CLAUDE_MODEL=claude-haiku-5-5`. To use a different model, remove the `#` and change the ID. Leave the line commented out to use the default. Do not leave it as a blank `CLAUDE_MODEL=`: that sets the model to an empty string, and every API call fails.

## Run the lab

```powershell
uv run jupyter lab
```

Jupyter opens in your browser. Open `lab.ipynb` and run the cells in order with **Shift+Enter**.

Start Jupyter with `uv run` from the project folder, so the notebook runs on the project's `.venv`. `solution.ipynb` is the complete reference solution if you want to compare.

## How the checkpoints work

Each part ends with a checkpoint that prints either `PASS: ...` or `NOT YET: ...` with a specific hint. Fix what the hint names, run the cell again, and move on when it says `PASS`.

- **Some checkpoints run offline.** `check_handler` and `check_drink_soon` call your function directly with fixed inputs and grade each case. `check_sommelier` checks what `ask_claude` would send, without sending it. They make no API calls, so they give the same answer every time.
- **Some checkpoints check a conversation.** Claude words its answers differently every time, so these checks never look for exact text. They check what must be true: the tool was called, every `tool_use` has a matching `tool_result`, the conversation ended with Claude's answer, and that answer names a vineyard your tool actually returned.
- **A checkpoint shares a cell with the function it checks.** Running the cell again always checks your latest code.
- **Two labels tell failures apart:**
  - **YOUR TURN:** the next cell is yours to finish. Each function you write starts as a single `raise NotImplementedError("YOUR TURN: ...")` line. Replace that line with your code. An error that starts with `YOUR TURN` is never one of the expected failures.
  - **EXPECTED TO FAIL:** the next cell shows a bug on purpose. Read the error, then move on.
- **Stuck?** Each exercise has collapsible **Hint** cells below it, from a nudge to the full code.
- **Before the stretch,** a gate checks that your Part 4 handler and dispatch function are finished. If they are not, it stops with `Finish Part 4 first:` and names what is missing.
- **At the end,** `lab_checks.summary()` lists every part with `PASS` or `NOT YET`. It re-runs the offline checks, and it reports the conversation checks that have passed since the kernel started. If you restarted the kernel, run those cells again.

## Troubleshooting

**`check_setup` says the key is not found.**
Check that `.env` is in the project folder (next to `cellar.json`, not inside `.venv`), and that the line reads `ANTHROPIC_API_KEY=` followed by your key, with no quotes or spaces. Then restart the kernel (**Kernel > Restart Kernel**) and run the notebook from the top. Instead of `.env`, you can also set the key in your shell before starting Jupyter:

```powershell
# Windows (PowerShell), in the same window you run Jupyter from
$env:ANTHROPIC_API_KEY = "sk-ant-..."
uv run jupyter lab
```

```bash
# macOS or Linux
export ANTHROPIC_API_KEY="sk-ant-..."
uv run jupyter lab
```

A key set in the shell takes priority over the one in `.env`. If an old key is set in your shell, it wins.

**`check_setup` says the notebook is running on the wrong kernel.**
The notebook is using a Python outside the project's `.venv`, so the lab's packages may be missing. Close Jupyter, then start it again from the project folder with `uv run jupyter lab`. In VS Code or another editor, select the interpreter in the project's `.venv` folder as the kernel.

**`ModuleNotFoundError` for a module inside `anthropic`, on Windows.**
Some files in the `anthropic` package have very long names. In a deeply nested folder, their full paths pass Windows' 260-character limit, and they are skipped during install. Clone the lab into a short path, such as `C:\Users\<you>\claude-tool-lab`, delete the `.venv` folder, and run `uv sync` again.

**Jupyter asks for a password or token.**
Open the full URL that `uv run jupyter lab` printed in your terminal. It includes `?token=` followed by a long string, and that logs you in. If you closed the terminal output, run this in another terminal in the project folder to print it again:

```powershell
uv run jupyter server list
```

**`AuthenticationError` (401).**
The API did not accept your key. Check that you copied the whole key, that it has not been revoked in the Console, and that `.env` no longer says `your-key-here`. After you edit `.env`, restart the kernel: running `load_dotenv()` again does not replace a key that is already loaded.

**`RateLimitError` (429).**
You sent too many requests in a short time, or your account's rate limit is low. Wait a minute and run the cell again. See <https://platform.claude.com/docs/en/api/rate-limits>.

**`NotFoundError` (404) mentioning the model.**
The model ID is wrong. If you set `CLAUDE_MODEL` in `.env`, check the ID against <https://platform.claude.com/docs/en/about-claude/models/overview>, or comment the line out to use the default. Then restart the kernel.

**The turn ended on `max_tokens`.**
The reply hit the `max_tokens` cap and was cut off. This model thinks before it answers, and thinking tokens count toward the cap. The lab uses `max_tokens=1024`. If you lowered it, set it back to 1024 or higher.

**`NotImplementedError: YOUR TURN: ...`**
You ran an exercise before writing it. This is not one of the expected failures. Replace the `raise NotImplementedError(...)` line in that function with your code.

**`PartNotFinishedError: Finish Part 4 first: ...`**
The stretch gate found that `check_cellar` or `dispatch_tool` is not finished. The message names which one. Go back to Part 4, finish it, run its cells again, and then run the gate again.

## Where to go next

- Tool use, in depth: <https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview>
- Streaming responses as they are generated: <https://platform.claude.com/docs/en/build-with-claude/streaming>
- Prompt caching, which makes repeated tool definitions and long prompts cheaper: <https://platform.claude.com/docs/en/build-with-claude/prompt-caching>
- API errors and how to handle them: <https://platform.claude.com/docs/en/api/errors>
- The Python SDK, including a tool runner that drives the loop you wrote by hand: <https://github.com/anthropics/anthropic-sdk-python>
- What this lab simplifies, and what the production version of the loop and the error handling looks like: [docs/instructor-notes.md](docs/instructor-notes.md#what-this-lab-simplifies)

To run the lab's own tests (no API calls): `uv run pytest`.
