# StressLens

> **Working prototype — Stage 2 in progress**  
> **Project owner: Satyam Tomar · Status updated: 19 November 2026**

### Earlier awareness during work

I started StressLens because I sometimes worked for long periods and only noticed mental fatigue or fogginess afterwards. The goal is to help an individual notice possible difficulties earlier, choose when to pause and understand personal work patterns through clear graphs and short explanations.

The current foundation is a local Python/Streamlit prototype with a work clock, voluntary check-ins, break reminders and descriptive charts. It works with the camera off. Reliable automatic stress or fatigue detection remains an unfinished, unvalidated research goal; the timer and check-ins do not complete that ambition.

**Python · Streamlit · pandas · Local-first demonstration**

![A fictional week with 14 invented check-ins across seven UTC days.](docs/images/fictional-week.png)

*This is a labelled demonstration with invented answers, not participant data.*

## Take a quick look

- [Project direction and next milestones](docs/PROJECT_DIRECTION.md): the original goal, current foundation and concrete next task.
- [Visual project brief](docs/Satyam_Tomar_StressLens.pdf): the earlier three-page portfolio snapshot; the current status is recorded here and in the project direction.
- [How I worked on it](docs/PORTFOLIO.md): the problem, design choices and code/test references.
- [Run it locally](docs/SETUP.md): setup, optional components and a short demonstration.
- [Verification record](docs/VERIFICATION.md): what was checked and what remains unverified.

The recovery branch adds **Work session → Your work-session report**: current/latest-ended session answers, categorical charts, factual wording and separate work-scoped JSON/TXT downloads. Closing answers after End require an explicit choice; older/restored history stays separate. A dated disposable browser journey and export comparison are recorded; broader user review remains pending.

## What the application does

| Area | What to expect |
|---|---|
| Work session | Start, pause, resume and end a work clock; only active time counts. |
| Check-ins | Record a voluntary response and optional clarity answer. Missing and unsure answers stay visible. |
| Fictional week | Explore 14 invented check-ins over seven UTC days, isolated from the personal session. |
| Charts | See descriptive category counts with denominators. |
| Reports | Export a separate session report as JSON or readable TXT. |
| Break reminders | Choose optional prompts within the updating app. |

The fictional-week view has no export. Reports do not infer stress from facial movement or combine self-reports and device readings into a health score. Optional face/text tools are exploratory and separate from the core demonstration.

## Continuing development

Start with [AGENTS.md](AGENTS.md) and the [project direction](docs/PROJECT_DIRECTION.md). They preserve the original aim and explain the code/data boundaries. The report is now reachable directly from Work session in the reviewed checkout. Its completed clock and current answers are transient, so durable session recovery needs a separate design and verification step.

## My contribution

I defined the use case, set priorities, requested changes and reviewed the experience. Codex helped with implementation, debugging, tests and documentation. The project demonstrates that collaborative process; I do not claim to have independently written every component or trained MediaPipe or Qwen.

## Development status

| Stage | Status | Scope |
|---|---|---|
| Stage 1 — local foundation | Prototype implemented; checks recorded on 20 October 2026 | Work clock, voluntary check-ins, optional break reminders, fictional-week charts and session reports. |
| Stage 2 — refinement and validation | In progress | Improve usability and reporting, check installation reproducibility and investigate optional camera performance. |
| Future user testing | Planned | Gather voluntary feedback after the local experience and consent flow are ready. |

Stage 2 is the current development phase, not a completed release. Stage 2 work includes:

- [x] Restore the original product goal and durable contributor instructions.
- [x] Keep unsure, skipped and expired responses explicit in the short summaries, and label the displayed check-in scope separately from active work time.
- [x] Make the work-session report easy to reach; check its chart and JSON/TXT parity in a disposable local browser journey.
- [ ] Review the report's clarity and responsive layout with the owner.
- [ ] Verify setup on a clean machine and document any reproducibility issues.
- [ ] Investigate optional camera throughput with aligned diagnostic measurements before choosing a fix.
- [ ] Record the results and remaining limitations before a wider prototype trial.

**Latest update — 19 November 2026:** the owner's VS Code workspace now opens this reviewed checkout without replacing the earlier source. A fictional camera-off browser journey showed the session chart and matching JSON/TXT exports. Restart returned the app to an empty work state, confirming that completed-session recovery is still unfinished. The dated [verification record](docs/VERIFICATION.md) includes an intermittent AppTest timeout and the exact passing repeat. Clean-machine installation and automatic detection remain unverified.

## Verification

On 20 October 2026, the existing development environment recorded **484 passing tests, 10 real-SDK skips and 7 passing subtests**, with Ruff clean. A separate model-free test scope from the source-only package recorded **208 passes**. These scopes overlap and their counts must not be added.

The October disposable browser checks covered the camera-off journey and report exports; the original 73-file release received a separate Codex QA archive review. The presentation snapshot preserved 63 source/test/config/asset files. Active development now continues beyond that snapshot, so its frozen-file condition and historical package manifest do not describe the current checkout. New checks and remaining limits are recorded separately in the [verification record](docs/VERIFICATION.md).

On 17 November 2026, the recovery patch recorded **210 passing model-free tests** and a clean Ruff check. One inherited pytest-plugin deprecation warning remains. These checks do not establish a full application installation, browser behavior or hardware performance.

## Scope

This is a local portfolio prototype. Physical-camera performance, scientific stress validation and installation on a clean machine remain unverified. The optional camera-rate decline has no established cause. Session state can be lost on reload or process loss; reminders are not operating-system notifications.

No project-code license has been selected. Retain [third-party attribution](assets/ATTRIBUTION.md) and review upstream terms before reusing optional models or data.
