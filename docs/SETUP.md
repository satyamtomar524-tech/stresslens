# Setup and demonstration

## Existing setup

Use the existing project environment and correct running preview. On Satyam's laptop the accepted preview uses port 8505. Do not start a duplicate server or interrupt an active session.

If the application is not running, the command is:

```powershell
.\.venv\Scripts\python.exe -B -m streamlit run app.py --server.address=127.0.0.1 --server.port=8505
```

Run it from the folder containing `app.py`, then open `http://127.0.0.1:8505/`. The development environment uses Windows and Python 3.13.15. File watching is disabled in the checked configuration. The supplied legacy launcher may use port 8501; use the explicit command above for 8505.

## New installation

This is the reproduction procedure. A clean-machine installation has not been verified.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -B -m streamlit run app.py --server.address=127.0.0.1 --server.port=8505
```

The lock includes optional model libraries, so the installation is larger than the camera-off demonstration. No dependency installation or upgrade was performed when this presentation copy was arranged.

## A 90-second camera-off demonstration

Use a disposable session with fictional inputs. Leave camera/SDK consent and saved history off.

1. **0-15 seconds:** show Work session. Explain that it records work time and voluntary answers.
2. **15-45 seconds:** open Explore a fictional week. Show the 14 invented check-ins, seven UTC days and missing/unsure categories.
3. **45-60 seconds:** choose Return to my session. Explain that the example does not add personal check-ins. Demonstrate Start/Pause only in the disposable session if time permits.
4. **60-75 seconds:** show check-in and reminder controls. Reminders are in-app prompts, not operating-system notifications; do not imply a full reminder interval elapsed.
5. **75-90 seconds:** explain the separate session-report exports and the AI-assisted contribution.

For a longer demo, save one clearly fictional check-in in the disposable session, then open **Live camera -> Your session report -> More details** without enabling the camera. JSON and TXT downloads describe that same report. Clear only the disposable report afterwards.

The fictional-week view has no export. Upload & text produces a separate result JSON. Manual/CSV readings do not establish a connection to a wearable.

## Optional components

The work clock, check-ins and fictional example need no downloaded face/Qwen weights or trained text artifact. Optional analysis has separate requirements.

| Component | Existing script | Boundary |
|---|---|---|
| Face measurements | `scripts/setup_models.py` | Downloads the face model; SDK consent is a separate choice. |
| English-text baseline | `scripts/train_text_model.py` | Downloads the authors' text release and trains/evaluates locally; review upstream terms first. |
| Local Qwen wording | `scripts/setup_explainer.py` | Downloads pinned model files and checks a weight checksum; source-note fallback is available. |

These scripts are reproduction references, not automatic setup steps. Raw datasets, private records, model weights and environments are excluded. Do not load an untrusted joblib/pickle artifact. Model and dataset rights are separate from any future project-code license.

## Persistence and limits

- Work state, current reports and the selected photo are held in the app session. Reload or process loss can lose unsaved state.
- Optional local check-in history is off by default. When enabled it is stored locally, is not encrypted by the app and is separate from the current report. Clearing a report does not delete saved history.
- Camera and SDK consent start off. Read the in-app SDK telemetry notice before enabling optional face processing; it is not described as zero outbound traffic.
- Facial coefficients describe visible movement. The text score is uncalibrated; Qwen supplies bounded wording. These do not establish a person's stress level.
- Closed-tab reminders, sleep recovery, scientific validity and a guaranteed camera sampling rate are not established.

See [verification and test commands](VERIFICATION.md).
