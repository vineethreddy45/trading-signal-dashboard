# Clean Trading Signal Dashboard

Daily and weekly EMA20/EMA30/volume signals, filtering, backtesting, Streamlit deployment, TradingView Pine Script, and scheduled email reports.

## 1. Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Windows PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

## 2. Create a brand-new public GitHub repository

Create an empty public repository named `trading-signal-dashboard`. Do not add a README or `.gitignore` on GitHub.

Then run:

```bash
git init
git add .
git commit -m "Initial clean trading signal project"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/trading-signal-dashboard.git
git push -u origin main
```

## 3. Deploy to Streamlit Community Cloud

Use:

- Repository: `YOUR_USERNAME/trading-signal-dashboard`
- Branch: `main`
- Main file: `app.py`

## 4. Configure email at 8 PM Eastern

GitHub repository → Settings → Secrets and variables → Actions.

Add:

- `SMTP_HOST`: `smtp.gmail.com`
- `SMTP_PORT`: `587`
- `SMTP_USERNAME`: your Gmail
- `SMTP_PASSWORD`: Google App Password
- `SMTP_USE_SSL`: optional, set to `true` for implicit SSL SMTP servers (default: `false`)
- `EMAIL_FROM`: your Gmail
- `EMAIL_TO`: recipient email

The workflow sends Daily signals every evening and includes Weekly signals on Friday. GitHub Actions may start a few minutes late.
If the required email secrets are not configured yet, the workflow logs a warning and skips the send step instead of failing the job.

Test from GitHub → Actions → Send Trading Signal Email → Run workflow.

## 5. TradingView

Paste `tradingview/ema20_ema30_volume_signals.pine` into Pine Editor and create Breakout Buy and Pullback Buy alerts.

Educational use only. Data can be delayed.
