# Automatic signal evaluation — research draft

**Status: proposal only.** No predictive accuracy, user benefit or clinical validity has been established. This plan authorizes no dataset access, model training, camera use, participant recruitment or external data sharing.

## One possible target

Evaluate whether a model can estimate an individual’s **voluntary self-reported stress category at a check-in**, based on explicitly consented observations from a predefined, short preceding window. This is a report of subjective experience, not a diagnosis or a direct measurement of stress. An optional answer of unsure, skipped or missing is not a low-stress label; record its frequency separately and exclude it from the primary classification target. No inference should be shown as a user-facing stress result on the basis of this proposal alone.

Before collecting or using data, define the exact answer scale, window and timing, allowed input features, treatment of repeated check-ins and missing observations, and data availability at prediction time. Do not use a future answer, post-check-in information or participant identifier as a predictive feature. Do not treat task condition or facial movement as a stress label.

## Rights, consent and data handling

Verify each dataset’s actual source, permitted uses, redistribution and retention restrictions before access or reuse; document the specific version and evidence. Obtain informed, revocable participant consent and specify retention, deletion, local storage and any sharing. Use only data necessary for the approved evaluation. No raw video or identifiable records are required merely to collect usability feedback. Dataset availability or permission to access is not permission to publish participant data. Resolve governance and access separately before any data collection or processing.

## Evaluation design

Split by participant **before** feature fitting, normalization, tuning or model selection: training, validation and locked final test participants must be disjoint. Keep all sessions and time windows from one person in the same split. Use training-only fitted preprocessing and participant-grouped cross-validation for development; reserve the final test for a prespecified evaluation after model and thresholds are frozen. Document all exclusions, duplicate checks, group sizes and any deviation. Separate a potential personalization study with a different protocol; do not mix its within-person results with performance on unseen people.

Compare against prespecified simple baselines, including the training-set majority category and a suitable context-only model if consented contextual features are available. Report baseline and candidate on the same participants and windows. Do not assume a balanced sample or equal performance across participants. Use participant-level resampling for uncertainty intervals and report per-participant variability, class support and subgroup results only where samples are sufficient and privacy permits. Insufficient support means **inconclusive**, not a positive result.

## Measures and decisions — not yet set

Before opening the locked test results, select primary and secondary metrics appropriate to the finalized scale, for example balanced accuracy or macro-F1, class-specific recall and precision, a confusion matrix, and calibration if probability estimates are used. State which mistakes matter most, how uncertain predictions are handled, and the false-alarm and missed-detection costs. Predeclare sample-size rationale, confidence-interval method, baseline comparison, acceptable missingness and coverage, calibration criteria and minimum meaningful improvement. **All numerical thresholds, acceptance criteria and sample sizes are undecided.** Do not select them after seeing results. Evaluate abstention and coverage together rather than reporting accuracy only among easy cases.

## Release gate

Publish aggregate methodology, actual dataset rights, sample counts, exclusions, baseline comparisons, uncertainty, failures and limitations; preserve a reproducible, privacy-safe evaluation record. An independent review must find the protocol and evidence appropriate for the intended claim. A predictive research result alone does not establish clinical validity, improved wellbeing, generalization to all users or suitability for continuous monitoring. User-facing deployment requires a separate decision, consent design and evidence for the exact intended use.
