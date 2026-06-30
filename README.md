# ChronoStress Study

ChronoStress is a Streamlit research platform for a 14-30 day experience-sampling study of chronic physiological stress and subjective time perception. It combines ecological momentary assessment (EMA), wearable physiology, behavioural timing tasks, and a brief Stroop task in one participant-facing workflow.

This is a research application, not a diagnostic or mental-health service.

## Included

- Participant registration, salted access-code hashing, sign-in, and consent records
- Daily EMA context, multi-item visual analogue scales, and conditional event questions
- Time reproduction, prospective timing, and time estimation tasks
- Eight-trial colour-word Stroop task with accuracy and reaction-time metrics
- Automatic signed and absolute timing error calculation
- Wearable integration boundary with deterministic Fitbit/Oura-style demonstration data
- SQLite storage with linked participant, assessment, wearable, task, and cognitive tables
- Longitudinal Plotly dashboards and within-person association plots
- Participant data export as CSV bundle, Excel workbook, and JSON
- Responsive custom Streamlit interface with light/dark theme compatibility

## Run Locally

From this project folder:

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Open the local URL printed in the terminal, normally `http://localhost:8501`.

Register a new demonstration participant from the welcome screen. Mock wearable observations are generated deterministically for that participant so the dashboard is populated immediately.

## Project Structure

```text
chrono-stress-study/
|-- app.py                    # Application entry point and navigation
|-- config.py                 # Study protocol configuration
|-- components/
|   `-- ui.py                 # Reusable design-system components
|-- database/
|   `-- repository.py         # Schema, transactions, queries, and mock seeding
|-- services/
|   |-- auth.py               # Access-code hashing and verification
|   `-- wearables.py          # Replaceable wearable provider interface
|-- utils/
|   |-- analytics.py          # Derived metrics and Plotly figures
|   `-- exports.py            # CSV, Excel, and JSON generation
|-- views/
|   |-- assessment.py         # EMA and behavioural task workflow
|   |-- auth.py               # Welcome, consent, registration, and login
|   `-- dashboard.py          # Dashboard, analytics, exports, and protocol
|-- .streamlit/config.toml    # Streamlit theme and server configuration
`-- requirements.txt
```

## Data Storage

The app creates `study_data.db` beside `app.py`. Every assessment is committed in one SQLite transaction so context, task, and cognitive records cannot be partially saved. The database is excluded from Git.

SQLite data on Streamlit Community Cloud is **not durable**: container restarts or redeployments can erase the local database. This is suitable for a professor-facing demonstration, but not for collecting live longitudinal research data. Before real recruitment, replace the repository connection with a persistent managed database such as PostgreSQL and complete the institution's data-protection review.

## Wearable Integration

`services/wearables.py` defines the provider boundary. `DemoWearableProvider` currently supplies reproducible mock observations. A real integration should add provider-specific OAuth, token storage, consent scopes, rate-limit handling, and scheduled synchronisation while preserving the same service boundary.

## Deploy to Streamlit Community Cloud

1. Create a new GitHub repository for this folder only.
2. Push the contents of `chrono-stress-study` so `app.py` and `requirements.txt` are at the repository root.
3. Sign in at [share.streamlit.io](https://share.streamlit.io) with GitHub.
4. Select **Create app**, choose the new repository and branch, and set the entry point to `app.py`.
5. Deploy the app. No secrets are required for the mock wearable demonstration.

Do not reuse the repository for the earlier timer app. Keeping each app in its own repository makes deployment and study history much clearer.

## Research Readiness

Before participant use, replace the illustrative consent language and support details with ethics-approved documents, verify task timing against the deployment environment, add researcher role-based access, use durable encrypted storage, define withdrawal/deletion procedures, and complete accessibility and device testing. Browser-based reaction times are useful for repeated within-person research but should not be presented as laboratory-grade millisecond timing without validation.

