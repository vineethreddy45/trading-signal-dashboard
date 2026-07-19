import argparse, html, os, smtplib, ssl
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
from dotenv import load_dotenv
from src.scanner import scan_symbols

ET=ZoneInfo("America/New_York")
KEEP=["BREAKOUT BUY","PULLBACK BUY","WATCH"]

def table(frame,title):
    frame=frame[frame.Signal.isin(KEEP)].copy()
    if frame.empty: return f"<h2>{title}</h2><p>No matching signals.</p>"
    cols=[c for c in ["Symbol","Market","Signal","Close","EMA20","EMA30","Volume Confirm","EMA20 > EMA30","Bar Date"] if c in frame.columns]
    frame=frame[cols]
    headers="".join(f"<th>{html.escape(c)}</th>" for c in cols)
    rows=[]
    for _,r in frame.iterrows():
        color={"BREAKOUT BUY":"#d9ead3","PULLBACK BUY":"#cfe2f3","WATCH":"#fff2cc"}.get(r.Signal,"white")
        rows.append(f"<tr style='background:{color}'>"+"".join(f"<td>{html.escape(str(v))}</td>" for v in r)+"</tr>")
    return f"<h2>{title}</h2><table><tr>{headers}</tr>{''.join(rows)}</table>"

def send(subject,body):
    load_dotenv()
    req=["SMTP_HOST","SMTP_PORT","SMTP_USERNAME","SMTP_PASSWORD","EMAIL_FROM","EMAIL_TO"]
    missing=[x for x in req if not os.getenv(x)]
    if missing: raise RuntimeError("Missing: "+", ".join(missing))
    msg=EmailMessage(); msg["Subject"]=subject; msg["From"]=os.environ["EMAIL_FROM"]; msg["To"]=os.environ["EMAIL_TO"]
    msg.set_content("HTML email required"); msg.add_alternative(body,subtype="html")
    ctx=ssl.create_default_context()
    with smtplib.SMTP(os.environ["SMTP_HOST"],int(os.environ["SMTP_PORT"])) as s:
        s.starttls(context=ctx); s.login(os.environ["SMTP_USERNAME"],os.environ["SMTP_PASSWORD"]); s.send_message(msg)

def main():
    p=argparse.ArgumentParser(); p.add_argument("--report",choices=["daily","weekly","both","auto"],default="auto"); p.add_argument("--force",action="store_true"); p.add_argument("--preview",action="store_true"); a=p.parse_args()
    now=datetime.now(ET)
    if not a.force and now.hour!=20: print("Skip: not 8 PM ET"); return
    report="both" if a.report=="auto" and now.weekday()==4 else ("daily" if a.report=="auto" else a.report)
    symbols=pd.read_csv("data/symbols.csv")
    parts=[table(scan_symbols(symbols,"Daily"),"Daily Signals")]
    if report in ["weekly","both"]: parts.append(table(scan_symbols(symbols,"Weekly"),"Weekly Signals"))
    body=f"<html><style>table{{border-collapse:collapse}}th,td{{border:1px solid #ccc;padding:6px}}</style><body><h1>Trading Signals</h1><p>{now:%Y-%m-%d %I:%M %p} ET</p>{''.join(parts)}</body></html>"
    if a.preview: Path("signal_email_preview.html").write_text(body); print("Preview created")
    else: send(f"{report.title()} Trading Signals — {now:%Y-%m-%d}",body); print("Email sent")
if __name__=="__main__": main()
