# StressLens: purpose and next milestones

**Owner: Satyam Tomar · Direction restored: 17 November 2026**

## The purpose to preserve

StressLens began with a personal problem: noticing mental fatigue, fogginess or stress only after working for a long time. The aim is to help an individual notice possible difficulties earlier, choose when to pause, and understand their own work patterns afterwards through simple graphs and a short explanation.

The long-term ambition includes investigating automatic signals, with an optional laptop camera. A timer and check-ins are useful foundations; they do not complete that ambition. A portfolio presentation explains the work but is not the product's purpose.

This brief records the owner's stated goal and the recovery priorities derived from reviewing the existing repository. The implementation choices below are working defaults, not evidence that a user trial or scientific validation has happened. A later explicit owner decision can change them; record the reason here so future work has context.

## What exists and what remains a goal

| Area | Current evidence | Next question |
|---|---|---|
| Work context | Start, pause, resume and end; active work time is separate from camera time. | Can someone finish and understand one real work session without searching through optional tools? |
| Voluntary answers | Stress and optional clarity check-ins; descriptive daily counts; optional local history. | Can the user distinguish this work session from earlier check-ins? |
| Reflection | A shared report ledger, JSON/TXT downloads and optional supplied measurements. | Can the person reach a useful report directly from Work session? |
| Camera and text | Experimental movement observations and a separate language baseline. | Are the measurements stable on the target laptop, and what would they validly predict? |
| Earlier awareness | User-selected in-app break intervals and voluntary reflection are implemented. | Are prompts and summaries understandable and useful during ordinary work? Benefits have not been established. |
| Automatic stress/fatigue inference | Unfinished and unvalidated. | Can a clearly defined target be evaluated independently before an inference is shown to users? |

Repository baseline reviewed: `d7f1eaee02f3d7f9f8634e9bf9a6ecea9ff5678e` (11 November 2026). See [verification](VERIFICATION.md) for dated checks and limits. Stage 2 remains in progress.

## The experience we are building toward

1. Open StressLens and start work with the camera off.
2. Optionally record how stressed and how clear-headed you feel now. An unsure or skipped answer remains visible as such.
3. Receive a reminder only if you enabled it; choose to pause, snooze or dismiss it. Explain that it is based on the selected interval.
4. End work and see active work time, the answers associated with that session, a readable chart and one or two factual sentences.
5. Review older personal check-ins only when their scope is clearly labelled and the user has chosen to retain history.
6. Use optional camera experiments separately, with a clear explanation of what was measured and what is still unknown.

Steps 4 and 5 need further product work. Current report exports describe the shared observation ledger, not a complete work-session archive. A work session's active duration cannot be recovered from the span between camera or check-in timestamps. Clarity and work-session association currently live in `CompanionState.extras`, outside the numeric report export. Do not promise that the present exports preserve them.

## Approach and boundaries

Continue incrementally in the existing Python/Streamlit application. Preserve the shared `ReportWorkspace` and the independent `WorkSession` clock. This reuses the tested foundation while making the everyday experience easier to follow.

A camera-first rewrite would put the main journey behind unresolved measurement and validity questions. A generic timer-only direction would lose the original ambition. The chosen working approach keeps a usable everyday tool and an explicit research path within one project, with separate evidence for each.

- Use deterministic summaries of recorded data first. Adding an LLM is not a substitute for deciding what a report should say.
- Label voluntary answers, camera movement, supplied device measurements and any future model inference by their source.
- Preserve zero/none, low, high, unsure, skipped, expired and absent observations. Never silently fill a gap or turn uncertainty into a reassuring score.
- Keep camera/SDK consent, saved history and model downloads explicit. Leave the core usable when optional components are unavailable.
- Keep fictional demonstrations isolated from personal state, history and reports.
- Keep session loss, history retention and export limitations visible. Changing storage or recovery behavior is a product decision, not a hidden implementation detail.

## Ordered milestones and completion evidence

### 1. Recover direction and establish a current baseline — this patch

- Add durable contributor instructions and this brief.
- Recheck the existing model-free suite and record the actual environment and outcome.
- Correct short summaries so uncertainty states and displayed-history scope remain explicit.
- Separate historical packaging/test records from current development claims.

Completion means those files and targeted checks exist. It does not mean Stage 2, a clean installation or automatic detection is complete.

### 2. Make one work session understandable — next product task

Build a report reachable from Work session, using the existing shared records. Show active work time separately from observation span and camera time. Define how the report selects the current or most recently ended work session; give standalone, older and restored check-ins their own clearly labelled scope.

A check-in saved after End work is currently standalone. Decide explicitly how a closing check-in should be associated; do not silently attach it to a finished session.

The smallest useful output is a descriptive view of that session's stress and clarity answers and one or two source-bound sentences. Do not interpolate an unobserved mood trajectory. If exports are extended, specify the schema and ensure the screen, JSON and TXT describe the same chosen scope. Keep existing camera-report downloads compatible or document an explicit migration.

**Completion evidence:** a disposable camera-off journey covering Start → check-in → Pause → Resume → End → report/export; an empty session; an unsure/skipped answer; a second session; restored history; and a cleared report. Confirm that no optional model is initialized, no fictional answers enter personal state, and no older answers are attributed to the current clock. Record any limitation discovered rather than hiding it.

### 3. Reproduce the everyday setup

Check the documented dependencies in a fresh environment and record exact versions, commands and failures. Consider separating core dependencies from optional camera/text/LLM libraries only after mapping current imports. Do not replace dependency pins simply to make one environment pass.

**Completion evidence:** a documented installation and camera-off journey from a clean environment, followed by a target Windows check. A Linux unit-test run is useful evidence, but does not establish either result.

### 4. Measure the optional camera path

On an explicitly chosen laptop, record capture rate, processed frames, valid samples, timing, coverage, resource use and stop/restart behavior over the same interval. Compare conditions before proposing a fix.

**Completion evidence:** a reproducible diagnostic record with hardware/software context, the observed failure and a measured comparison if a change is made. There is no established slowdown cause or guaranteed 10 Hz rate today.

### 5. Learn from voluntary use

Prepare a small, voluntary usability trial after the local journey and data choices are clear. Ask whether check-ins, reminders and summaries were understandable, useful or intrusive. Decide in advance what participants retain locally and what they choose to share; do not require raw camera recordings for usability feedback.

**Completion evidence:** an agreed trial procedure, feedback questions, explicit data handling and recorded findings with the actual participant count. Usability feedback alone does not validate stress inference or prove improved wellbeing.

### 6. Evaluate automatic signals as research

Keep this milestone visible. Define one target at a time: a person's reported stress, reported fatigue, a task condition and a visible movement are different targets. Before training, specify the reference labels, permitted data use, participant-separated evaluation, comparison baseline and criteria for false alarms, uncertainty and usefulness. Keep data preparation and evaluation independent enough to avoid subject or time leakage.

UBFC-Phys investigations mentioned in the project history do not establish a trained or validated predictor. Dataset access, camera throughput and software test counts are not prediction accuracy. Only expose an automatic inference after its actual evaluation supports the stated use; otherwise retain the observations as exploratory measurements.

## Next coding-session instruction

Read `AGENTS.md`, this brief and `docs/VERIFICATION.md`. Start with milestone 2 unless the owner supplies a different priority. First inspect how `WorkSession.session_id`, `CompanionState.extras`, optional restored history and the shared `ReportWorkspace` relate. Propose the smallest report view that can identify its data scope honestly, then implement and verify that bounded change. Do not start a rewrite, add a new model or treat the whole roadmap as one task.
