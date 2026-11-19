# StressLens project recovery implementation plan

**Goal:** restore the original product direction and fix the short summaries' handling of uncertainty and data scope.

**Architecture:** retain the existing work clock, shared report workspace, exports and UI layout. Change only pure summary generation and its regression checks; record the next user-journey milestone separately.

**Stack:** Python, existing pytest checks; existing Streamlit/pandas application unchanged at its UI boundary.

**Spec:** [Project direction](../../PROJECT_DIRECTION.md).

## Constraints and review focus

Keep historical verification dated. Distinguish the current work clock from all check-ins shown, and distinguish unsure from skipped/expired. Preserve true zero ratings and existing camera coverage/interruption language. Empty data must not imply reassurance. Make no new persistence, camera, export-schema or model change.

## Tasks

- [x] Inspect the repository baseline, current code paths and historical verification; obtain independent direction and architecture reviews.
- [x] Add `AGENTS.md` and `docs/PROJECT_DIRECTION.md`, with the original ambition and one concrete next milestone.
- [x] In `tests/test_output_summaries.py`, update the existing mixed-state fixtures and add report fixtures covering answered/unsure/skipped/expired values. Add an empty-work fixture and verify source data remains unchanged. Run the file before the fix and confirm the failures describe the missing distinctions.
- [x] In `stresslens/output_summaries.py`, retain the `work_overview(state, elapsed_seconds, summary)` and `report_overview(snapshot)` interfaces. Count each explicit state from its source, label work time separately from the displayed check-in scope, and preserve existing camera wording. No schema or view changes.
- [x] Run the summary tests and the documented seven-file model-free scope. Record exact environment/results and any warning. Run syntax/lint checks available for the modified source; do not claim a full application/browser or hardware check.
- [x] Align README, portfolio purpose and verification wording. Mark `PACKAGE_MANIFEST.json` explicitly as historical instead of claiming its old hashes inventory the active checkout. Keep its original hashes and results as historical data.
- [x] Independently review the diff and evidence; address the two wording clarifications and verify the final code hashes.

**Delivery target:** a separate branch and draft pull request, with the remaining Stage 2 product/research work visible.

## Acceptance

The patch is complete when a future coding session can identify the original goal and next task from repository instructions, the public status remains accurate, and actual summary outputs retain uncertainty states and identify their scope. This is a recovery increment, not completion of the work-session report milestone or automatic stress detection.

## Execution notes

The focused regressions failed as expected before the change (4 failed, 8 passed), then passed (12 passed). The final model-free scope returned 210 passes and one inherited AnyIO/pytest deprecation warning; Ruff 0.17.0 passed. Existing CRLF documentation endings were retained, so whitespace verification explicitly accepts CR at line endings. Historical manifest hashes were preserved rather than regenerated as if they described this checkout. See `docs/VERIFICATION.md` for evidence and limits.

Review clarification: clarity uses "rated" rather than "supplied" so an explicit unsure response is not described as absent. The two affected assertions failed before that correction; the final 210-test scope and Ruff check passed afterwards. The README checklist now correctly introduces completed and open work together.

Final review: no critical or important findings and no remaining minor findings. Current-session filtering, closing check-in association, clarity exports and full session archives remain the explicitly scoped next product task. Upstream validated input contracts remain in place. AppTests, browser/Windows behavior, hardware and inference validity were not claimed.
