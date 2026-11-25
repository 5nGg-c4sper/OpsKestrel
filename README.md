
<h1 align="center">Self-Operating Computer Framework</h1>

<p align="center">
  <strong>A framework to enable multimodal models to operate a computer.</strong>
</p>
<p align="center">
  Using the same inputs and outputs as a human operator, the model views the screen and decides on a series of mouse and keyboard actions to reach an objective. Released Nov 2023, the Self-Operating Computer Framework was one of the first examples of full computer-use. 
</p>

## SOC Agent: deterministic macOS automation

This repository also contains a secondary-development runtime named `soc_agent`.
It executes versioned JSON tasks through deterministic desktop actions and uses a
vision model only for screenshot verification.

Documentation:

- [Product roadmap](docs/ROADMAP.md)
- [Architecture](docs/ARCHITECTURE.md)

Configure the project root `.env` from [.env.example](.env.example).

Run one task:

```bash
./venv/bin/soc-agent run tasks/calculator_17x23.json
```

Run the parameterized calculator task:

```bash
./venv/bin/soc-agent run tasks/calculator_parameterized.json \
  --param right=23
```

`calculator_parameterized.json` defaults `left` to `17`, `operator` to `*`, and
`expected_result` to `391`. `right` has no default and must be supplied with
`--param`.

Override several string parameters by repeating `--param`:

```bash
./venv/bin/soc-agent run tasks/calculator_parameterized.json \
  --param left=3 \
  --param right=4 \
  --param expected_result=12
```

Task strings can reference declared parameters with `${parameter_name}` in
fields such as `app`, `content`, `keys`, `prompt`, and `summary`. Referencing an
undeclared or missing parameter fails before the first desktop action.
`verify_vision` steps accept `expected_vision_result` (default `true`), plus
`verification_attempts` and `verification_retry_delay_seconds` for retrying
transient screenshot or model results.

Add an explicit approval checkpoint before a high-risk action:

```json
{
  "type": "approval",
  "prompt": "是否允许提交这份客户资料？"
}
```

The approval step always asks the configured confirmation handler. Approval
continues to the next step; rejection cancels the task. `--non-interactive`
treats approval checkpoints as rejected. Reports store `approval_prompt` and
`approval_result` on the step.

Sensitive screen regions can be blacked out before any screenshot is uploaded
to the vision model or copied into report artifacts:

```json
{
  "redaction_regions": [
    {
      "x": 0.0,
      "y": 0.1,
      "width": 0.35,
      "height": 0.2
    }
  ]
}
```

Coordinates are normalized to `0-1` relative to the screenshot. Every
verification screenshot and failure screenshot in the task is redacted before
it is exposed to another component.

Run all JSON tasks in a directory:

```bash
./venv/bin/soc-agent suite tasks/
```

Pass shared parameters to every task in a suite:

```bash
./venv/bin/soc-agent suite tasks/ --param right=23
```

Every task in a parameterized suite must declare each shared parameter. A task
that does not declare a supplied parameter fails with an unknown parameter
error.

Every task still writes its own report and artifacts. After the suite finishes,
SOC Agent also writes a summary report under `reports/` named
`<timestamp>-<suite-name>.json` and prints its path:

```text
Suite: tasks
Total: 2
Passed: 2
Failed: 0
Timed out: 0
Cancelled: 0
Duration: 8.72 seconds
Report: reports/20261124-090000-tasks.json
```

The suite report includes overall counts, status, timing, whether execution
stopped early, and every nested task result. Task `report_path` and
`failure_log` values are preserved so an inspector can trace the summary back
to the original diagnostics:

```json
{
  "suite_name": "tasks",
  "status": "passed",
  "total": 1,
  "passed": 1,
  "failed": 0,
  "timed_out": 0,
  "cancelled": 0,
  "stopped_early": false,
  "results": [
    {
      "task_name": "calculator_17x23",
      "status": "passed",
      "report_path": "reports/20261124-090000-calculator_17x23.json",
      "failure_log": null
    }
  ],
  "report_path": "reports/20261124-090000-tasks.json"
}
```

Suite names are sanitized for filenames. A repeated run with the same timestamp
uses a `-1`, `-2`, and subsequent suffix instead of overwriting an earlier
report.

Run a data-driven task dataset:

```bash
./venv/bin/soc-agent dataset datasets/calculator_cases.json
```

Each dataset case supplies its own parameters. Dataset commands therefore do
not accept `--param`. The task path inside a dataset is resolved relative to the
dataset file's directory.

Every case creates its own task report and screenshot artifacts. After all cases
finish, a summary report containing case names, parameters, statuses, durations,
and nested task reports is written under `reports/` as
`<timestamp>-<dataset-name>.json`.

Dataset cases retry only `failed` results, never `cancelled` or `timed_out`
results. Retry configuration is optional:

```json
{
  "name": "default_17x23",
  "parameters": {"right": "23"},
  "attempts": 2,
  "retry_delay_seconds": 0.5
}
```

`attempts` includes the initial execution and accepts values from 1 to 3.

Datasets can also load one case per CSV row:

```bash
./venv/bin/soc-agent dataset datasets/calculator_csv.json
```

The dataset maps CSV columns to task parameters:

```json
{
  "name": "calculator_csv_regression",
  "task": "../tasks/calculator_parameterized.json",
  "data_source": {
    "type": "csv",
    "path": "calculator_rows.csv",
    "case_name_column": "case_id",
    "parameters": {
      "left": "left",
      "operator": "operator",
      "right": "right",
      "expected_result": "expected_result"
    }
  }
}
```

The referenced CSV uses its headers as data fields:

```csv
case_id,left,operator,right,expected_result
case_17x23,17,*,23,391
case_125_div_5,125,/,5,25
```

Each row becomes an independent case and task report. When `parameters` is
omitted, every column except `case_name_column` is mapped to a task parameter
with the same name. Missing columns, empty values, repeated case names, and
malformed CSV rows stop dataset loading before any desktop action begins.
CSV source settings can also define default `attempts` and
`retry_delay_seconds` for every generated case.

Use either inline `cases` or `data_source`, not both.

Run the safe multi-record TextEdit workflow:

```bash
./venv/bin/soc-agent dataset datasets/textedit_csv.json
```

Each CSV row opens a new TextEdit document, writes a customer record, checks
the expected customer and note with the vision verifier, then closes the
document without saving. The source data is in
[datasets/textedit_rows.csv](datasets/textedit_rows.csv).

Run an ordered multi-task workflow:

```bash
./venv/bin/soc-agent workflow workflows/textedit_calculator.json \
  --param customer_name=张三 \
  --param note=首次联系
```

The example first writes and verifies a TextEdit record, then performs the
parameterized calculator task. Each task owns its own cleanup, so the TextEdit
document and calculator window are closed independently.
Each child task writes its own JSON report. After the workflow finishes, a
summary report is written under `reports/` with the ordered task statuses,
parameters, durations, nested task reports, cleanup result, and whether
execution stopped early.

Run the same workflow once for every CSV row:

```bash
./venv/bin/soc-agent dataset datasets/textedit_workflow_csv.json
```

This dataset uses the `workflow` target instead of `task`. Every CSV case runs
the complete ordered workflow with its own parameters, workflow report, nested
task reports, and final dataset summary entry.

Manage the persistent execution queue:

```bash
./venv/bin/soc-agent queue enqueue task \
  tasks/calculator_parameterized.json \
  --param right=23 \
  --priority 5 \
  --allow-app 计算器 \
  --allow-action open_app \
  --allow-action write \
  --allow-action press \
  --allow-action verify_vision \
  --allow-action done \
  --require-label office-mac

./venv/bin/soc-agent queue enqueue workflow \
  workflows/textedit_calculator.json \
  --param customer_name=张三 \
  --param note=首次联系

./venv/bin/soc-agent queue list
./venv/bin/soc-agent queue workers
./venv/bin/soc-agent queue run
./venv/bin/soc-agent queue run --drain
./venv/bin/soc-agent queue run --stale-after-seconds 3600 --max-attempts 3
./venv/bin/soc-agent queue run --worker-id macbook-runner-1
./venv/bin/soc-agent queue run --label office-mac
```

The queue is stored in `reports/queue.db` by default. `queue run` processes one
job by default, `--max-jobs` limits a batch, and `--drain` processes until no
pending jobs remain. Enqueuing and listing do not require the API key; running
the worker initializes the desktop environment and vision provider. Running
jobs whose claim lease expires are automatically returned to `pending` or
failed after `--max-attempts`.

Each Worker also receives a unique ID. While a job is executing, a background
heartbeat renews `claimed_at`; heartbeats and completion are rejected unless
the Worker still owns the job. `--worker-id` can provide a stable identity for
managed runners.

`queue workers` shows recently active Worker IDs, hostnames, PIDs, current
jobs, and last heartbeat times. Use `--online-within-seconds` to control the
online window.

`--require-label` restricts a job to Workers advertising every required label.
`queue run --label` advertises capabilities for the current Worker. Matching is
case-insensitive; jobs with no required labels can run on any Worker.

`--allow-app` and `--allow-action` create a per-job execution permission
profile. When omitted, the default SafetyPolicy remains in effect. When
present, access outside the allowlist cancels the task before the unauthorized
desktop action runs.

Stop immediately when a case does not pass:

```bash
./venv/bin/soc-agent dataset datasets/calculator_cases.json \
  --stop-on-failure
```

Failure diagnostics can be verified with the intentionally failing dataset:

```bash
./venv/bin/soc-agent dataset datasets/calculator_failure_case.json
```

This command is expected to return exit code `1`. Each non-passed task writes a
`failure.log` beside its report artifacts, and the task JSON report links to it
through `failure_log`. Dataset output also prints failed case names, attempt
counts, errors, task reports, and failure log paths.

Run the safe cross-application activation example:

```bash
./venv/bin/soc-agent run tasks/examples/multi_app_activate.json
```

`open_app` starts or opens an application. `activate_app` explicitly brings an
application to the foreground, including applications already opened earlier in
the same task.

Any regular step can include a vision `condition`. When the condition does not
match, the step is recorded as `skipped` and the task continues:

```bash
./venv/bin/soc-agent run tasks/examples/conditional_step_skip.json
```

Condition diagnostics include the prompt, expected and actual values, condition
duration, and an archived `condition_screenshot`. These fields are also shown
in terminal output and included in failure logs when condition evaluation fails.

Deterministic steps can repeat without duplicating JSON:

```bash
./venv/bin/soc-agent run tasks/examples/loop_write.json
```

`loop.count` is the total execution count and `loop.delay_seconds` is the delay
between iterations. Conditions are evaluated once before entering a loop.

Tasks can define `setup_steps` and `cleanup_steps` around the main `steps`:

```bash
./venv/bin/soc-agent run tasks/examples/setup_cleanup.json
```

Setup runs before the main flow. Cleanup runs after success, failure, timeout, or
early completion. A cleanup failure changes a previously passed task to failed,
but does not replace an existing main-flow failure.

For local development without the installed command, use
`./venv/bin/python -m soc_agent` with the same arguments.

The package must be installed in editable mode after changing entry points:

```bash
./venv/bin/python -m pip install -e .
```

If the environment uses legacy `setuptools` without editable-install support,
use `./venv/bin/python setup.py develop` instead.

Each task produces a JSON report under `reports/`. Suite and dataset commands
also produce their own summary reports. Verification screenshots are archived
under `reports/artifacts/<report-name>/`. Reports and screenshots are ignored by
Git because they may contain sensitive desktop content.

## Manual macOS GUI CI

The `macOS GUI Smoke` GitHub Actions workflow runs deterministic tasks on a
self-hosted Mac in a logged-in GUI session. It is manual-only and never runs on
pushes or pull requests, preventing ordinary CI jobs from taking control of a
developer desktop.

Prepare the self-hosted runner:

1. Register a repository-level macOS runner and add the custom `soc-gui` label.
2. Start the runner from Terminal while the same user is logged into an
   unlocked desktop session. Do not install it as a background-only service.
3. Grant the runner host application Accessibility and Screen Recording
   permissions in macOS System Settings.
4. Create the repository secret `OPENAI_API_KEY`.
5. Optionally create the repository variable `OPENAI_BASE_URL`. It defaults to
   `https://api.siliconflow.cn/v1`.

From GitHub, open **Actions**, select **macOS GUI Smoke**, choose the task and
model, then run the workflow. Only a small allowlist of reviewed tasks is
available. Report upload is disabled by default because screenshots may contain
sensitive desktop content; enable `upload_reports` only when a seven-day private
artifact is acceptable.

The project keeps the original MIT license and remains a derivative of the
OthersideAI Self-Operating Computer project.

<div align="center">
  <img src="https://github.com/OthersideAI/self-operating-computer/blob/main/readme/self-operating-computer.png" width="750"  style="margin: 10px;"/>
</div>

<!--
:rotating_light: **OUTAGE NOTIFICATION: gpt-4o**
**This model is currently experiencing an outage so the self-operating computer may not work as expected.**
-->


## Key Features
- **Compatibility**: Designed for various multimodal models.
- **Integration**: Includes OpenAI-compatible vision branches for **Qwen3-VL, DeepSeek-VL and GPT-4o**.
- **Future Plans**: Support for additional models.

## Demo
https://github.com/OthersideAI/self-operating-computer/assets/42594239/9e8abc96-c76a-46fb-9b13-03678b3c67e0


## Run `Self-Operating Computer`

1. **Install the project**
```
pip install self-operating-computer
```
2. **Run the project**
```
operate
```
3. **Enter your OpenAI Key**: If you don't have one, you can obtain an OpenAI key [here](https://platform.openai.com/account/api-keys). If you need you change your key at a later point, run `vim .env` to open the `.env` and replace the old key. 

<div align="center">
  <img src="https://github.com/OthersideAI/self-operating-computer/blob/main/readme/key.png" width="300"  style="margin: 10px;"/>
</div>

4. **Give Terminal app the required permissions**: As a last step, the Terminal app will ask for permission for "Screen Recording" and "Accessibility" in the "Security & Privacy" page of Mac's "System Preferences".

<div align="center">
  <img src="https://github.com/OthersideAI/self-operating-computer/blob/main/readme/terminal-access-1.png" width="300"  style="margin: 10px;"/>
  <img src="https://github.com/OthersideAI/self-operating-computer/blob/main/readme/terminal-access-2.png" width="300"  style="margin: 10px;"/>
</div>

## Using `operate` Modes

#### OpenAI models

The active model is read from `MODEL` in `.env`. If `MODEL` is not set, the command-line default is `gpt-4-with-ocr`.

```
operate -m o1-with-ocr
```

To experiment with OpenAI's latest `gpt-4.1` model, run:

```
operate -m gpt-4.1-with-ocr
```


### Multimodal Models  `-m`
Try Google's `gemini-pro-vision` by following the instructions below. Start `operate` with the Gemini model
```
operate -m gemini-pro-vision
```

**Enter your Google AI Studio API key when terminal prompts you for it** If you don't have one, you can obtain a key [here](https://makersuite.google.com/app/apikey) after setting up your Google AI Studio account. You may also need [authorize credentials for a desktop application](https://ai.google.dev/palm_docs/oauth_quickstart). It took me a bit of time to get it working, if anyone knows a simpler way, please make a PR.

#### Try Claude `-m claude-3`
Use Claude 3 with Vision to see how it stacks up to GPT-4-Vision at operating a computer. Navigate to the [Claude dashboard](https://console.anthropic.com/dashboard) to get an API key and run the command below to try it. 

```
operate -m claude-3
```

#### Try Qwen3-VL with SiliconFlow

Create an API key in the [SiliconFlow dashboard](https://cloud.siliconflow.cn/), then configure the project root `.env` file:

```env
MODEL=Qwen/Qwen3-VL-8B-Instruct
OPENAI_API_KEY='your SiliconFlow API key'
OPENAI_BASE_URL=https://api.siliconflow.cn/v1
```

`Qwen/Qwen3-VL-32B-Instruct` can be used instead of the 8B model when higher visual reasoning quality is more important than latency.
When `MODEL` is set in `.env`, it takes precedence over the `-m` command-line argument.

```bash
./venv/bin/operate --verbose --prompt "打开备忘录"
```

#### Try LLaVa Hosted Through Ollama `-m llava`
If you wish to experiment with the Self-Operating Computer Framework using LLaVA on your own machine, you can with Ollama!   
*Note: Ollama currently only supports MacOS and Linux. Windows now in Preview*   

First, install Ollama on your machine from https://ollama.ai/download.   

Once Ollama is installed, pull the LLaVA model:
```
ollama pull llava
```
This will download the model on your machine which takes approximately 5 GB of storage.   

When Ollama has finished pulling LLaVA, start the server:
```
ollama serve
```

That's it! Now start `operate` and select the LLaVA model:
```
operate -m llava
```   
**Important:** Error rates when using LLaVA are very high. This is simply intended to be a base to build off of as local multimodal models improve over time.

Learn more about Ollama at its [GitHub Repository](https://www.github.com/ollama/ollama)

### Voice Mode `--voice`
The framework supports voice inputs for the objective. Try voice by following the instructions below. 
**Clone the repo** to a directory on your computer:
```
git clone https://github.com/OthersideAI/self-operating-computer.git
```
**Cd into directory**:
```
cd self-operating-computer
```
Install the additional `requirements-audio.txt`
```
pip install -r requirements-audio.txt
```
**Install device requirements**
For mac users:
```
brew install portaudio
```
For Linux users:
```
sudo apt install portaudio19-dev python3-pyaudio
```
Run with voice mode
```
operate --voice
```

### Optical Character Recognition Mode `-m gpt-4-with-ocr`
The Self-Operating Computer Framework now integrates Optical Character Recognition (OCR) capabilities with the `gpt-4-with-ocr` mode. This mode gives GPT-4 a hash map of clickable elements by coordinates. GPT-4 can decide to `click` elements by text and then the code references the hash map to get the coordinates for that element GPT-4 wanted to click. 

Based on recent tests, OCR performs better than `som` and vanilla GPT-4 so we made it the default for the project. To use the OCR mode you can simply write: 

 `operate` or `operate -m gpt-4-with-ocr` will also work. 

### Set-of-Mark Prompting `-m gpt-4-with-som`
The Self-Operating Computer Framework now supports Set-of-Mark (SoM) Prompting with the `gpt-4-with-som` command. This new visual prompting method enhances the visual grounding capabilities of large multimodal models.

Learn more about SoM Prompting in the detailed arXiv paper: [here](https://arxiv.org/abs/2310.11441).

For this initial version, a simple YOLOv8 model is trained for button detection, and the `best.pt` file is included under `model/weights/`. Users are encouraged to swap in their `best.pt` file to evaluate performance improvements. If your model outperforms the existing one, please contribute by creating a pull request (PR).

Start `operate` with the SoM model

```
operate -m gpt-4-with-som
```



## Contributions are Welcomed!:

If you want to contribute yourself, see [CONTRIBUTING.md](https://github.com/OthersideAI/self-operating-computer/blob/main/CONTRIBUTING.md).

## Feedback

For any input on improving this project, feel free to reach out to [Josh](https://twitter.com/josh_bickett) on Twitter. 

## Join Our Discord Community

For real-time discussions and community support, join our Discord server. 
- If you're already a member, join the discussion in [#self-operating-computer](https://discord.com/channels/877638638001877052/1181241785834541157).
- If you're new, first [join our Discord Server](https://discord.gg/YqaKtyBEzM) and then navigate to the [#self-operating-computer](https://discord.com/channels/877638638001877052/1181241785834541157).

## Follow HyperWriteAI for More Updates

Stay updated with the latest developments:
- Follow HyperWriteAI on [Twitter](https://twitter.com/HyperWriteAI).
- Follow HyperWriteAI on [LinkedIn](https://www.linkedin.com/company/othersideai/).

## Compatibility
- This project is compatible with Mac OS, Windows, and Linux (with X server installed).

## OpenAI Rate Limiting Note
The ```gpt-4o``` model is required. To unlock access to this model, your account needs to spend at least \$5 in API credits. Pre-paying for these credits will unlock access if you haven't already spent the minimum \$5.   
Learn more **[here](https://platform.openai.com/docs/guides/rate-limits?context=tier-one)**
