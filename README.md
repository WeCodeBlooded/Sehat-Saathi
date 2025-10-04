# Sehat Saathi

Modern healthcare assistant platform.

## Features
1. Chatbot: Symptom guidance with personalized context from prior health history (translation aware).
2. Tele‑Counselling Scheduler: Create and list appointments (Firestore subcollection `appointments`).
3. Hospital Locator: Uses OpenStreetMap Overpass API + heuristic / zero‑shot AI recommendation when available.
4. Health History: Add and view symptom records (Firestore subcollection `health_history`).

## Frontend (React + Vite)
Path: `frontend/`

Environment variable (optional):
`VITE_BACKEND_URL` (default: `http://localhost:5000`)

Run:
```bash
npm install
npm run dev
```

## Backend (Flask)
Path: `backend/`

Run:
```bash
pip install -r requirements.txt
python app.py
```

## Configuration
- Firebase Admin: place `serviceAccountKey.json` in `backend/`.
- Hugging Face (optional AI hospital specialty suggestion): set `HUGGINGFACE_API_TOKEN`.
- Gemini AI presently disabled / placeholder logic retained in code.

## Security Notes
- Do not commit real service account keys publicly.
- Add rate limiting & auth hardening for production.

## License
Internal / Hackathon prototype (add proper license).
