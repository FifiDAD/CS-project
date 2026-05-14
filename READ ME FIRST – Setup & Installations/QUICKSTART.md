# QUICKSTART — TradeWatch dashboard

Quickstart guide — Full guide is in `SETUP GUIDE.md`. (please visit this if you encountered any issues during Quickstart installation process)

---

## Run it in 4 commands

```bash
cd "<unzipped folder>/CS PROJECT/CS-project"
pip install -r "READ ME FIRST – Setup & Installations/requirements.txt"
streamlit run app.py
# then open http://localhost:8501 in your browser
```

Press `Ctrl + C` in the terminal to stop the server.

---

## Things to know

- **API keys are already filled in** at `CS-project/.env`. You do not need
  to register for anything.
- **The trained ML model** ships at `CS-project/models/eta_xgb.joblib`. The
  dashboard uses it on first launch — no training step required.
- **The AIS history database** (`CS-project/.ais_positions.db`, ~380 MB) is
  included. It populates the ETA Quality page's plotly scatter plot the
  moment you launch.
- **Do NOT delete** any of: `.env`, `.ais_positions.db`, `models/`,
  `.streamlit/`. They are the project state.
- **First-launch order**: the Landing page opens first → click "Open Main
  Dashboard →" → vessels appear within ~30 seconds as the AIS WebSocket
  connects.

If anything misbehaves, jump to the **Troubleshooting** section near the
bottom of `SETUP GUIDE.md`.
