from __future__ import annotations

import argparse
from datetime import datetime
from email.message import EmailMessage
import html
import os
from pathlib import Path
import smtplib
import ssl
import sys
from zoneinfo import ZoneInfo

import pandas as pd
from dotenv import load_dotenv

from src.scanner import scan_symbols


EASTERN = ZoneInfo("America/New_York")
STATE_FILE = Path("data/email_signal_state.csv")

EMAIL_SIGNALS = {
    "BREAKOUT BUY",
    "WATCH",
}


def snapshot_signals(
    filtered: pd.DataFrame,
    timeframe: str,
) -> pd.DataFrame:
    if filtered.empty:
        return pd.DataFrame(
            columns=[
                "Timeframe",
                "Symbol",
                "Signal",
                "Bar Date",
            ]
        )

    snap = filtered[["Symbol", "Signal", "Bar Date"]].copy()
    snap["Timeframe"] = timeframe
    snap["Symbol"] = snap["Symbol"].astype(str)
    snap["Signal"] = snap["Signal"].astype(str)
    snap["Bar Date"] = snap["Bar Date"].astype(str)
    return snap[["Timeframe", "Symbol", "Signal", "Bar Date"]]


def load_previous_state() -> pd.DataFrame:
    if not STATE_FILE.exists():
        return pd.DataFrame(
            columns=[
                "Timeframe",
                "Symbol",
                "Signal",
                "Bar Date",
            ]
        )
    previous = pd.read_csv(STATE_FILE)
    expected = {"Timeframe", "Symbol", "Signal", "Bar Date"}
    if not expected.issubset(previous.columns):
        return pd.DataFrame(
            columns=[
                "Timeframe",
                "Symbol",
                "Signal",
                "Bar Date",
            ]
        )
    return previous[list(expected)].astype(str)


def detect_signal_changes(
    current_state: pd.DataFrame,
    previous_state: pd.DataFrame,
) -> pd.DataFrame:
    if current_state.empty:
        return current_state
    if previous_state.empty:
        return current_state

    merged = current_state.merge(
        previous_state,
        on=["Timeframe", "Symbol"],
        how="left",
        suffixes=("", "_prev"),
    )
    changed = merged[
        (merged["Signal_prev"].isna())
        | (merged["Signal"] != merged["Signal_prev"])
        | (merged["Bar Date"] != merged["Bar Date_prev"])
    ]
    return changed[["Timeframe", "Symbol", "Signal", "Bar Date"]].copy()


def persist_state(current_state: pd.DataFrame) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    current_state.drop_duplicates(
        subset=["Timeframe", "Symbol"],
        keep="last",
    ).to_csv(STATE_FILE, index=False)


def should_send_email_report(
    daily_count: int,
    weekly_count: int,
    *,
    send_empty_summary: bool = True,
) -> bool:
    """Keep the daily report cadence even when no signal rows qualify."""
    return send_empty_summary or daily_count > 0 or weekly_count > 0


def load_symbols() -> pd.DataFrame:
    file_path = Path("data/symbols.csv")

    if not file_path.exists():
        raise FileNotFoundError(
            "data/symbols.csv was not found."
        )

    symbols = pd.read_csv(file_path)

    required_columns = {
        "symbol",
        "market",
        "display_symbol",
    }

    missing_columns = required_columns.difference(
        symbols.columns
    )

    if missing_columns:
        raise ValueError(
            "symbols.csv is missing columns: "
            f"{sorted(missing_columns)}"
        )

    return symbols.dropna(
        subset=[
            "symbol",
            "market",
            "display_symbol",
        ]
    )


def filter_email_signals(
    results: pd.DataFrame,
) -> pd.DataFrame:
    """
    Include a stock only when:

    1. Signal is BREAKOUT BUY or WATCH.
    2. Close is above EMA20.
    3. Close is above EMA30.
    """

    if results.empty:
        return results

    required_columns = {
        "Signal",
        "Close > EMA20",
        "Close > EMA30",
    }

    missing_columns = required_columns.difference(
        results.columns
    )

    if missing_columns:
        raise ValueError(
            "Scanner output is missing columns: "
            f"{sorted(missing_columns)}"
        )

    filtered = results[
        results["Signal"].isin(EMAIL_SIGNALS)
        & (results["Close > EMA20"] == True)
        & (results["Close > EMA30"] == True)
    ].copy()

    signal_order = {
        "BREAKOUT BUY": 1,
        "WATCH": 2,
    }

    filtered["_signal_order"] = (
        filtered["Signal"]
        .map(signal_order)
        .fillna(99)
    )

    filtered = filtered.sort_values(
        [
            "_signal_order",
            "Market",
            "Symbol",
        ]
    )

    return filtered.drop(
        columns="_signal_order"
    )


def create_html_table(
    results: pd.DataFrame,
    title: str,
) -> str:
    filtered = filter_email_signals(results)

    if filtered.empty:
        return f"""
        <h2>{html.escape(title)}</h2>
        <p>
            No Breakout Buy or Watch stocks
            closed above both EMA20 and EMA30.
        </p>
        """

    display_columns = [
        "Symbol",
        "Market",
        "Signal",
        "Close",
        "EMA20",
        "EMA30",
        "Volume Confirm",
        "EMA20 > EMA30",
        "Bar Date",
    ]

    available_columns = [
        column
        for column in display_columns
        if column in filtered.columns
    ]

    display = filtered[
        available_columns
    ].copy()

    for column in [
        "Close",
        "EMA20",
        "EMA30",
    ]:
        if column in display.columns:
            display[column] = display[column].map(
                lambda value: (
                    f"{value:,.2f}"
                    if pd.notna(value)
                    else ""
                )
            )

    header_html = "".join(
        f"<th>{html.escape(str(column))}</th>"
        for column in display.columns
    )

    table_rows = []

    for _, row in display.iterrows():
        signal = str(row["Signal"])

        if signal == "BREAKOUT BUY":
            background = "#d9ead3"
        else:
            background = "#fff2cc"

        cell_html = "".join(
            f"<td>{html.escape(str(value))}</td>"
            for value in row.tolist()
        )

        table_rows.append(
            f"""
            <tr style="background:{background}">
                {cell_html}
            </tr>
            """
        )

    signal_counts = (
        filtered["Signal"]
        .value_counts()
    )

    breakout_count = int(
        signal_counts.get(
            "BREAKOUT BUY",
            0,
        )
    )

    watch_count = int(
        signal_counts.get(
            "WATCH",
            0,
        )
    )

    return f"""
    <h2>{html.escape(title)}</h2>

    <p>
        <strong>
            Breakout Buy: {breakout_count}
            |
            Watch: {watch_count}
        </strong>
    </p>

    <table>
        <thead>
            <tr>
                {header_html}
            </tr>
        </thead>

        <tbody>
            {''.join(table_rows)}
        </tbody>
    </table>
    """


def build_email_report(
    limit: int | None = None,
) -> tuple[str, datetime, list[tuple[str, str, bytes]], bool, pd.DataFrame]:
    symbols = load_symbols()

    daily_results = scan_symbols(
        symbols_df=symbols,
        timeframe="Daily",
        limit=limit,
    )
    print(
        f"Daily scan completed: {len(daily_results)} rows "
        f"(limit={limit})"
    )

    weekly_results = scan_symbols(
        symbols_df=symbols,
        timeframe="Weekly",
        limit=limit,
    )
    print(
        f"Weekly scan completed: {len(weekly_results)} rows "
        f"(limit={limit})"
    )

    current_time_et = datetime.now(EASTERN)

    daily_filtered = filter_email_signals(daily_results)
    weekly_filtered = filter_email_signals(weekly_results)

    current_state = pd.concat(
        [
            snapshot_signals(daily_filtered, "Daily"),
            snapshot_signals(weekly_filtered, "Weekly"),
        ],
        ignore_index=True,
    )
    previous_state = load_previous_state()
    changed_state = detect_signal_changes(current_state, previous_state)

    daily_changed_symbols = set(
        changed_state.loc[
            changed_state["Timeframe"] == "Daily",
            "Symbol",
        ].astype(str)
    )
    weekly_changed_symbols = set(
        changed_state.loc[
            changed_state["Timeframe"] == "Weekly",
            "Symbol",
        ].astype(str)
    )

    daily_changes = daily_filtered[
        daily_filtered["Symbol"].astype(str).isin(daily_changed_symbols)
    ].copy()
    weekly_changes = weekly_filtered[
        weekly_filtered["Symbol"].astype(str).isin(weekly_changed_symbols)
    ].copy()

    daily_csv = daily_filtered.to_csv(index=False).encode("utf-8")
    weekly_csv = weekly_filtered.to_csv(index=False).encode("utf-8")

    daily_count = len(daily_filtered)
    weekly_count = len(weekly_filtered)
    daily_changed_count = len(daily_changes)
    weekly_changed_count = len(weekly_changes)
    should_send = should_send_email_report(
        daily_count,
        weekly_count,
    )

    print(
        "Email summary counts: "
        f"daily={daily_count}, weekly={weekly_count}, "
        "changed_daily="
        f"{daily_changed_count}, changed_weekly={weekly_changed_count}, "
        f"should_send={should_send}."
    )

    email_body = f"""
    <html>
        <head>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    color: #1f2328;
                }}

                p {{
                    font-size: 14px;
                    line-height: 1.6;
                }}

                strong {{
                    color: #163a5f;
                }}
            </style>
        </head>

        <body>
            <h1>Daily and Weekly Trading Signal Report</h1>

            <p>Generated at {current_time_et:%Y-%m-%d %I:%M %p} Eastern Time.</p>

            <p>
                Attached are the filtered signal CSV files.
                Daily rows: <strong>{daily_count}</strong>.
                Weekly rows: <strong>{weekly_count}</strong>.
            </p>

            <p>
                Signal changes since previous run:
                Daily: <strong>{daily_changed_count}</strong>,
                Weekly: <strong>{weekly_changed_count}</strong>.
            </p>

            <p>
                Filter: <strong>BREAKOUT BUY</strong> or <strong>WATCH</strong>
                with close above both <strong>EMA20</strong> and <strong>EMA30</strong>.
            </p>

            <hr>

            <p style="font-size:12px;color:#666">
                Educational research only. Market data may be delayed.
            </p>
        </body>
    </html>
    """

    attachments = [
        ("daily_signals.csv", "text/csv", daily_csv),
        ("weekly_signals.csv", "text/csv", weekly_csv),
        (
            "daily_signal_changes.csv",
            "text/csv",
            daily_changes.to_csv(index=False).encode("utf-8"),
        ),
        (
            "weekly_signal_changes.csv",
            "text/csv",
            weekly_changes.to_csv(index=False).encode("utf-8"),
        ),
    ]

    return email_body, current_time_et, attachments, should_send, current_state


def save_report_preview(
    html_body: str,
    attachments: list[tuple[str, str, bytes]],
    generated_time: datetime,
) -> Path:
    output_dir = Path("signal_reports") / generated_time.strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)

    preview_file = output_dir / "signal_email_preview.html"
    preview_file.write_text(html_body, encoding="utf-8")

    for filename, _, content in attachments:
        (output_dir / filename).write_bytes(content)

    print(
        "Saved report preview and attached CSVs to:",
        output_dir.resolve(),
    )

    return output_dir


def log_status(status: str, reason: str) -> None:
    print(f"Email report status: {status} | reason: {reason}")


def send_email(
    subject: str,
    html_body: str,
    attachments: list[tuple[str, str, bytes]],
) -> None:
    load_dotenv()

    required_settings = [
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "EMAIL_FROM",
        "EMAIL_TO",
    ]

    missing_settings = [
        setting
        for setting in required_settings
        if not os.getenv(setting)
    ]

    if missing_settings:
        raise RuntimeError(
            "Missing email settings: "
            + ", ".join(missing_settings)
        )

    recipients = [
        address.strip()
        for address
        in os.environ["EMAIL_TO"].split(",")
        if address.strip()
    ]

    if not recipients:
        raise RuntimeError(
            "EMAIL_TO does not contain a recipient."
        )

    print(
        "Preparing to send email to:",
        ", ".join(recipients),
    )

    message = EmailMessage()

    message["Subject"] = subject
    message["From"] = os.environ["EMAIL_FROM"]
    message["To"] = ", ".join(recipients)

    message.set_content(
        "Open this email in an HTML-compatible email client."
    )

    message.add_alternative(
        html_body,
        subtype="html",
    )

    for filename, mimetype, content in attachments:
        maintype, subtype = mimetype.split("/", 1)
        message.add_attachment(
            content,
            maintype=maintype,
            subtype=subtype,
            filename=filename,
        )

    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(
        os.environ["SMTP_PORT"]
    )
    smtp_username = os.environ[
        "SMTP_USERNAME"
    ]
    smtp_password = os.environ[
        "SMTP_PASSWORD"
    ]

    use_ssl = (
        os.getenv(
            "SMTP_USE_SSL",
            "false",
        ).lower()
        == "true"
    )

    ssl_context = ssl.create_default_context()
    if not use_ssl:
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

    if use_ssl:
        with smtplib.SMTP_SSL(
            smtp_host,
            smtp_port,
            context=ssl_context,
            timeout=60,
        ) as smtp:
            smtp.login(
                smtp_username,
                smtp_password,
            )
            print("SMTP SSL login succeeded.")

            smtp.send_message(message)
            print("SMTP SSL message sent.")

    else:
        with smtplib.SMTP(
            smtp_host,
            smtp_port,
            timeout=60,
        ) as smtp:
            smtp.ehlo()
            smtp.starttls(
                context=ssl_context
            )
            smtp.ehlo()

            smtp.login(
                smtp_username,
                smtp_password,
            )
            print("SMTP login succeeded.")

            smtp.send_message(message)
            print("SMTP message sent.")


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Send even when the current "
            "Eastern time is not 8 PM."
        ),
    )

    parser.add_argument(
        "--preview",
        action="store_true",
        help=(
            "Generate an HTML preview "
            "without sending email."
        ),
    )

    args = parser.parse_args()

    current_time_et = datetime.now(EASTERN)
    print(
        "Email report started at ET: "
        f"{current_time_et:%Y-%m-%d %I:%M %p}"
    )

    if (
        not args.force
        and current_time_et.hour != 20
    ):
        log_status(
            "skipped",
            "current time is outside the 8 PM ET send window",
        )

        return

    try:
        html_body, generated_time, attachments, should_send, current_state = build_email_report(limit=20)

        if not should_send and not args.preview:
            print(
                "No Daily or Weekly signals met the EMA20/EMA30 filter. "
                "The report is still being sent because the daily summary "
                "schedule is enabled."
            )

        subject = (
            "Daily + Weekly EMA20/EMA30 Signals — "
            f"{generated_time:%Y-%m-%d}"
        )

        if args.preview:
            preview_file = Path(
                "signal_email_preview.html"
            )

            preview_file.write_text(
                html_body,
                encoding="utf-8",
            )

            print(
                "Preview created: "
                f"{preview_file.resolve()}"
            )
            log_status(
                "preview",
                "HTML preview was generated without sending email",
            )

            return

        preview_dir = save_report_preview(
            html_body=html_body,
            attachments=attachments,
            generated_time=generated_time,
        )

        send_email(
            subject=subject,
            html_body=html_body,
            attachments=attachments,
        )

        persist_state(current_state)

        log_status(
            "sent",
            "email was generated and delivered successfully",
        )

    except Exception as exc:
        print("Email report failed:", str(exc), file=sys.stderr)
        log_status("failed", str(exc))
        raise


if __name__ == "__main__":
    main()