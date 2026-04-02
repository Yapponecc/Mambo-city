import json
import logging
import os
import sqlite3
import threading
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any
from wsgiref.simple_server import make_server


def load_dotenv_if_present() -> None:
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return

    try:
        with open(env_path, "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError as exc:
        logging.warning("Cannot read .env file: %s", exc)


load_dotenv_if_present()

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8080"))
RAW_DB_PATH = os.getenv("DB_PATH", "applications.db")
APP_TITLE = os.getenv("APP_TITLE", "Mambo City | Staff Applications")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "").strip()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip()
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

MIN_PASS_SCORE = 4
RESOLVED_DB_PATH = ""

QUIZ_QUESTIONS = [
    {
        "id": "q1",
        "question": "Can you use cheats/macros/xray on the server?",
        "options": [
            ("a", "No, any cheats or unfair advantage are forbidden."),
            ("b", "Yes, if I do it only sometimes."),
            ("c", "Yes, if nobody notices."),
        ],
        "correct": "a",
    },
    {
        "id": "q2",
        "question": "What is the right behavior in chat?",
        "options": [
            ("a", "Spam and insults are okay."),
            ("b", "Keep respectful communication, no hate/harassment."),
            ("c", "Only admins must be respectful."),
        ],
        "correct": "b",
    },
    {
        "id": "q3",
        "question": "Can you destroy or steal other players' builds/items?",
        "options": [
            ("a", "No, griefing/theft are forbidden."),
            ("b", "Yes, if I am strong enough."),
            ("c", "Yes, only in protected zones."),
        ],
        "correct": "a",
    },
    {
        "id": "q4",
        "question": "Can you advertise other projects/servers in chat?",
        "options": [
            ("a", "Yes, all ads are welcome."),
            ("b", "Only if I ask random players first."),
            ("c", "No, external ads are not allowed without admin approval."),
        ],
        "correct": "c",
    },
    {
        "id": "q5",
        "question": "You found a bug/exploit. What should you do?",
        "options": [
            ("a", "Use it for personal gain."),
            ("b", "Report it to staff/admin."),
            ("c", "Sell it to other players."),
        ],
        "correct": "b",
    },
]

RULES_SUMMARY = [
    "No cheats, xray, macros, dupes, or any unfair advantage.",
    "Respect players and staff in chat and gameplay.",
    "No griefing, theft, or intentional world damage.",
    "No external advertising without approval.",
    "Report bugs/exploits instead of abusing them.",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_db_path() -> str:
    global RESOLVED_DB_PATH
    if RESOLVED_DB_PATH:
        return RESOLVED_DB_PATH

    base_dir = os.path.dirname(os.path.abspath(__file__))
    preferred = RAW_DB_PATH if os.path.isabs(RAW_DB_PATH) else os.path.join(base_dir, RAW_DB_PATH)
    fallback = os.path.join(tempfile.gettempdir(), "staff-applications.db")

    for candidate in (preferred, fallback):
        try:
            parent = os.path.dirname(candidate) or "."
            os.makedirs(parent, exist_ok=True)
            conn = sqlite3.connect(candidate)
            conn.execute("CREATE TABLE IF NOT EXISTS __db_check (id INTEGER PRIMARY KEY)")
            conn.close()
            RESOLVED_DB_PATH = candidate
            if candidate != preferred:
                logging.warning("DB path '%s' failed, using fallback '%s'.", preferred, fallback)
            return RESOLVED_DB_PATH
        except sqlite3.Error as exc:
            logging.warning("Cannot use DB path '%s': %s", candidate, exc)

    raise RuntimeError("Unable to initialize SQLite database path.")


def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(resolve_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db_connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                minecraft_nick TEXT NOT NULL,
                age INTEGER NOT NULL,
                telegram_contact TEXT NOT NULL,
                timezone_label TEXT,
                playtime TEXT NOT NULL,
                motivation TEXT NOT NULL,
                status TEXT NOT NULL,
                quiz_score INTEGER,
                quiz_total INTEGER,
                decision_by TEXT,
                decision_reason TEXT,
                tg_chat_id INTEGER,
                tg_message_id INTEGER
            )
            """
        )


def create_application(data: dict[str, str]) -> int:
    current = now_iso()
    with db_connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO applications (
                created_at,
                updated_at,
                minecraft_nick,
                age,
                telegram_contact,
                timezone_label,
                playtime,
                motivation,
                status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                current,
                current,
                data["minecraft_nick"],
                int(data["age"]),
                data["telegram_contact"],
                data.get("timezone_label", ""),
                data["playtime"],
                data["motivation"],
                "quiz_pending",
            ),
        )
        return int(cursor.lastrowid)


def get_application(application_id: int) -> sqlite3.Row | None:
    with db_connect() as conn:
        row = conn.execute(
            "SELECT * FROM applications WHERE id = ?",
            (application_id,),
        ).fetchone()
        return row


def set_quiz_result(application_id: int, score: int, total: int, passed: bool) -> None:
    status = "pending_review" if passed else "quiz_failed"
    with db_connect() as conn:
        conn.execute(
            """
            UPDATE applications
            SET status = ?, quiz_score = ?, quiz_total = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, score, total, now_iso(), application_id),
        )


def set_telegram_message_meta(application_id: int, chat_id: int, message_id: int) -> None:
    with db_connect() as conn:
        conn.execute(
            """
            UPDATE applications
            SET tg_chat_id = ?, tg_message_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (chat_id, message_id, now_iso(), application_id),
        )


def set_decision(application_id: int, approved: bool, moderator: str) -> bool:
    new_status = "approved" if approved else "rejected"
    with db_connect() as conn:
        cursor = conn.execute(
            """
            UPDATE applications
            SET status = ?, decision_by = ?, updated_at = ?
            WHERE id = ? AND status = 'pending_review'
            """,
            (new_status, moderator, now_iso(), application_id),
        )
        return cursor.rowcount > 0


def parse_body(environ: dict[str, Any]) -> dict[str, str]:
    try:
        content_length = int(environ.get("CONTENT_LENGTH", "0") or "0")
    except ValueError:
        content_length = 0
    body = environ["wsgi.input"].read(content_length).decode("utf-8", errors="ignore")
    parsed = urllib.parse.parse_qs(body, keep_blank_values=True)
    return {k: v[0].strip() for k, v in parsed.items()}


def query_params(environ: dict[str, Any]) -> dict[str, str]:
    parsed = urllib.parse.parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True)
    return {k: v[0].strip() for k, v in parsed.items()}


def read_static_file(relative_path: str) -> bytes | None:
    safe_path = relative_path.strip("/").replace("\\", "/")
    full_path = (STATIC_DIR / safe_path).resolve()
    if not str(full_path).startswith(str(STATIC_DIR.resolve())):
        return None
    if not full_path.exists() or not full_path.is_file():
        return None
    try:
        return full_path.read_bytes()
    except OSError:
        return None


def static_response(start_response, content: bytes, content_type: str):
    start_response(
        "200 OK",
        [
            ("Content-Type", content_type),
            ("Content-Length", str(len(content))),
            ("Cache-Control", "public, max-age=3600"),
        ],
    )
    return [content]


def html_page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(title)}</title>
  <link rel="stylesheet" href="/static/style.css?v=1" />
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <h1>{escape(APP_TITLE)}</h1>
      <p>Submit form -> pass mini rules test -> get Telegram review result.</p>
    </div>
    {body}
  </div>
</body>
</html>"""


def response(start_response, status: str, body: str, headers: list[tuple[str, str]] | None = None):
    final_headers = [("Content-Type", "text/html; charset=utf-8")]
    if headers:
        final_headers.extend(headers)
    encoded = body.encode("utf-8")
    final_headers.append(("Content-Length", str(len(encoded))))
    start_response(status, final_headers)
    return [encoded]


def redirect(start_response, location: str):
    start_response("302 Found", [("Location", location), ("Content-Length", "0")])
    return [b""]


def home_form(error: str = "", values: dict[str, str] | None = None) -> str:
    values = values or {}
    error_block = f'<div class="error">{escape(error)}</div>' if error else ""
    rules_html = "".join(f"<li>{escape(rule)}</li>" for rule in RULES_SUMMARY)
    return html_page(
        APP_TITLE,
        f"""
        <div class="panel steps">
          <div class="step active">
            <div><span class="step-number">1</span><span class="step-title">Fill application</span></div>
            <div class="step-sub">Player fills contact and motivation fields.</div>
          </div>
          <div class="step">
            <div><span class="step-number">2</span><span class="step-title">Pass mini test</span></div>
            <div class="step-sub">5 questions about basic rules. Pass score is required.</div>
          </div>
          <div class="step">
            <div><span class="step-number">3</span><span class="step-title">Telegram review</span></div>
            <div class="step-sub">Admin approves or rejects from Telegram buttons.</div>
          </div>
        </div>

        <div class="panel">
          {error_block}
          <h2 style="margin-top:0">Staff Application Form</h2>
          <p class="muted">Complete all fields, then click the big button at the bottom to continue to the mini-test.</p>
          <div class="grid">
            <div>
              <label>Minecraft Nick</label>
              <input name="minecraft_nick" form="app-form" placeholder="Example: Yapponecc" value="{escape(values.get("minecraft_nick", ""))}" required />
              <div class="field-help">Exactly your in-game nickname.</div>
            </div>
            <div>
              <label>Age</label>
              <input name="age" type="number" min="10" max="99" form="app-form" value="{escape(values.get("age", ""))}" required />
              <div class="field-help">Allowed range: 10-99.</div>
            </div>
            <div>
              <label>Telegram Contact</label>
              <input name="telegram_contact" form="app-form" placeholder="@username or id" value="{escape(values.get("telegram_contact", ""))}" required />
              <div class="field-help">For feedback after moderation.</div>
            </div>
            <div>
              <label>Timezone</label>
              <input name="timezone_label" form="app-form" placeholder="Europe/Moscow" value="{escape(values.get("timezone_label", ""))}" />
              <div class="field-help">Optional but useful for scheduling.</div>
            </div>
            <div class="full">
              <label>Playtime / Experience</label>
              <textarea name="playtime" form="app-form" required>{escape(values.get("playtime", ""))}</textarea>
            </div>
            <div class="full">
              <label>Why do you want to join staff?</label>
              <textarea name="motivation" form="app-form" required>{escape(values.get("motivation", ""))}</textarea>
            </div>
            <div class="full">
              <label><input style="width:auto" type="checkbox" name="agree_rules" form="app-form" value="yes" {"checked" if values.get("agree_rules") else ""} /> I read the basic server rules.</label>
            </div>
          </div>
          <ul class="rules">{rules_html}</ul>
          <div class="hint">After clicking the button, player goes to the mini-test page automatically.</div>
          <form id="app-form" method="post" action="/apply">
            <button class="btn big" type="submit">Continue to Mini-Test -></button>
          </form>
        </div>
        """,
    )


def quiz_page(application_id: int, error: str = "") -> str:
    error_block = f'<div class="error">{escape(error)}</div>' if error else ""
    question_blocks = []
    for index, q in enumerate(QUIZ_QUESTIONS, start=1):
        options = []
        for key, label in q["options"]:
            options.append(
                f'<label style="text-transform:none;letter-spacing:0;font-weight:600;margin:6px 0;">'
                f'<input style="width:auto" type="radio" name="{escape(q["id"])}" value="{escape(key)}" required /> '
                f'{escape(label)}</label>'
            )
        block = (
            f'<div class="panel"><h3 style="margin-top:0">Q{index}. {escape(q["question"])}</h3>'
            f'{"".join(options)}</div>'
        )
        question_blocks.append(block)

    body = (
        f'<div class="panel steps">'
        f'<div class="step"><div><span class="step-number">1</span><span class="step-title">Application done</span></div>'
        f'<div class="step-sub">Basic form submitted successfully.</div></div>'
        f'<div class="step active"><div><span class="step-number">2</span><span class="step-title">Mini test now</span></div>'
        f'<div class="step-sub">Select one answer in each question.</div></div>'
        f'<div class="step"><div><span class="step-number">3</span><span class="step-title">Telegram review</span></div>'
        f'<div class="step-sub">Starts only if test is passed.</div></div></div>'
        f'<div class="panel">{error_block}<h2 style="margin-top:0">Mini Rule-Test</h2>'
        f'<p class="muted">Pass score: {MIN_PASS_SCORE}/{len(QUIZ_QUESTIONS)}. '
        f'Only passed applications go to Telegram moderation.</p>'
        f'<div class="hint">Tip: answer all questions before pressing the final button below.</div></div>'
        f'<form method="post" action="/quiz"><input type="hidden" name="id" value="{application_id}" />'
        f'{"".join(question_blocks)}'
        f'<div class="panel"><button class="btn big" type="submit">Submit Test and Send Application</button></div></form>'
    )
    return html_page("Mini Test", body)


def status_label(status: str) -> str:
    mapping = {
        "quiz_pending": "Quiz Pending",
        "quiz_failed": "Quiz Failed",
        "pending_review": "Pending Review",
        "approved": "Approved",
        "rejected": "Rejected",
    }
    return mapping.get(status, status)


def status_page(row: sqlite3.Row | None) -> str:
    if row is None:
        return html_page(
            "Status",
            '<div class="panel"><div class="error">Application not found. Check the status link/id.</div></div>',
        )

    status = row["status"]
    score_info = ""
    if row["quiz_score"] is not None and row["quiz_total"] is not None:
        score_info = f'<p><strong>Quiz score:</strong> {row["quiz_score"]}/{row["quiz_total"]}</p>'

    note = ""
    if status == "quiz_failed":
        note = (
            '<div class="error">Mini-test was not passed. Contact admin if retry is allowed.</div>'
        )
    elif status == "pending_review":
        note = '<div class="ok">Passed. Application is waiting for Telegram moderator decision.</div>'
    elif status == "approved":
        note = '<div class="ok">Approved. Staff team will contact you in Telegram.</div>'
    elif status == "rejected":
        note = '<div class="error">Rejected by moderation.</div>'

    body = f"""
      <div class="panel">
        <h2 style="margin-top:0">Application #{row['id']}</h2>
        <p><strong>Minecraft nick:</strong> {escape(row['minecraft_nick'])}</p>
        <p><strong>Status:</strong> <span class="status-pill {escape(status)}">{escape(status_label(status))}</span></p>
        {score_info}
        {note}
        <div class="hint">Keep this page link - status updates here automatically after decision.</div>
      </div>
    """
    return html_page("Application status", body)


def validate_application_form(data: dict[str, str]) -> tuple[bool, str]:
    required_fields = ["minecraft_nick", "age", "telegram_contact", "playtime", "motivation"]
    for field in required_fields:
        if not data.get(field, "").strip():
            return False, f"Field '{field}' is required."

    if data.get("agree_rules") != "yes":
        return False, "You must confirm that rules are read."

    try:
        age = int(data["age"])
    except ValueError:
        return False, "Age must be a valid number."

    if age < 10 or age > 99:
        return False, "Age must be between 10 and 99."

    if len(data.get("minecraft_nick", "")) > 32:
        return False, "Minecraft nick is too long."

    return True, ""


def score_quiz(data: dict[str, str]) -> int:
    score = 0
    for question in QUIZ_QUESTIONS:
        if data.get(question["id"]) == question["correct"]:
            score += 1
    return score


def telegram_api_call(method: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    if not TELEGRAM_BOT_TOKEN:
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            return json.loads(raw)
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        logging.warning("Telegram API call failed (%s): %s", method, exc)
        return None


def telegram_enabled() -> bool:
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_ADMIN_CHAT_ID)


def format_application_message(row: sqlite3.Row) -> str:
    lines = [
        f"<b>New application #{row['id']}</b>",
        "",
        f"<b>Minecraft:</b> {escape(row['minecraft_nick'])}",
        f"<b>Age:</b> {row['age']}",
        f"<b>Telegram:</b> {escape(row['telegram_contact'])}",
    ]
    if row["timezone_label"]:
        lines.append(f"<b>Timezone:</b> {escape(row['timezone_label'])}")
    lines.extend(
        [
            "",
            "<b>Playtime / Experience</b>",
            escape(row["playtime"]),
            "",
            "<b>Motivation</b>",
            escape(row["motivation"]),
            "",
            f"<b>Quiz:</b> {row['quiz_score']}/{row['quiz_total']}",
        ]
    )
    if PUBLIC_BASE_URL:
        lines.append(f"\n<b>Status page:</b> {escape(PUBLIC_BASE_URL)}/status?id={row['id']}")
    return "\n".join(lines)


def send_application_to_telegram(application_id: int) -> None:
    if not telegram_enabled():
        return

    row = get_application(application_id)
    if row is None or row["status"] != "pending_review":
        return

    payload = {
        "chat_id": TELEGRAM_ADMIN_CHAT_ID,
        "parse_mode": "HTML",
        "text": format_application_message(row),
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "✅ Approve", "callback_data": f"approve:{application_id}"},
                    {"text": "❌ Reject", "callback_data": f"reject:{application_id}"},
                ]
            ]
        },
    }
    result = telegram_api_call("sendMessage", payload)
    if result and result.get("ok"):
        msg = result.get("result", {})
        set_telegram_message_meta(
            application_id,
            int(msg.get("chat", {}).get("id", 0)),
            int(msg.get("message_id", 0)),
        )


def format_reviewed_message(row: sqlite3.Row) -> str:
    status = "APPROVED" if row["status"] == "approved" else "REJECTED"
    mod = row["decision_by"] or "unknown"
    return (
        f"<b>Application #{row['id']} — {status}</b>\n\n"
        f"<b>Minecraft:</b> {escape(row['minecraft_nick'])}\n"
        f"<b>Quiz:</b> {row['quiz_score']}/{row['quiz_total']}\n"
        f"<b>Moderator:</b> {escape(mod)}"
    )


def handle_callback(callback_query: dict[str, Any]) -> None:
    if not telegram_enabled():
        return

    callback_id = callback_query.get("id")
    message = callback_query.get("message", {})
    chat = message.get("chat", {})
    chat_id = str(chat.get("id", ""))
    data = callback_query.get("data", "")
    user = callback_query.get("from", {})
    moderator = user.get("username") or user.get("first_name") or "admin"

    if chat_id != str(TELEGRAM_ADMIN_CHAT_ID):
        telegram_api_call(
            "answerCallbackQuery",
            {"callback_query_id": callback_id, "text": "Not allowed here.", "show_alert": False},
        )
        return

    action, _, raw_id = data.partition(":")
    if action not in {"approve", "reject"} or not raw_id.isdigit():
        telegram_api_call(
            "answerCallbackQuery",
            {"callback_query_id": callback_id, "text": "Invalid action.", "show_alert": False},
        )
        return

    app_id = int(raw_id)
    changed = set_decision(app_id, approved=(action == "approve"), moderator=moderator)
    if not changed:
        telegram_api_call(
            "answerCallbackQuery",
            {"callback_query_id": callback_id, "text": "Already reviewed.", "show_alert": False},
        )
        return

    row = get_application(app_id)
    if row is not None:
        telegram_api_call(
            "editMessageText",
            {
                "chat_id": message.get("chat", {}).get("id"),
                "message_id": message.get("message_id"),
                "parse_mode": "HTML",
                "text": format_reviewed_message(row),
            },
        )

    telegram_api_call(
        "answerCallbackQuery",
        {"callback_query_id": callback_id, "text": "Saved.", "show_alert": False},
    )


def telegram_polling_loop() -> None:
    if not telegram_enabled():
        logging.warning("Telegram moderation disabled (missing TELEGRAM_BOT_TOKEN or TELEGRAM_ADMIN_CHAT_ID).")
        return

    logging.info("Telegram polling thread started.")
    offset = 0
    while True:
        payload = {
            "offset": offset,
            "timeout": 25,
            "allowed_updates": ["callback_query"],
        }
        response_data = telegram_api_call("getUpdates", payload)
        if not response_data or not response_data.get("ok"):
            time.sleep(2)
            continue

        for update in response_data.get("result", []):
            offset = update.get("update_id", offset) + 1
            callback_query = update.get("callback_query")
            if callback_query:
                handle_callback(callback_query)


def app(environ: dict[str, Any], start_response):
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET").upper()

    if path.startswith("/static/") and method == "GET":
        rel = path[len("/static/") :]
        data = read_static_file(rel)
        if data is None:
            return response(
                start_response,
                "404 Not Found",
                html_page("Not found", '<div class="panel"><div class="error">Static file not found.</div></div>'),
            )
        content_type = "application/octet-stream"
        if rel.endswith(".css"):
            content_type = "text/css; charset=utf-8"
        elif rel.endswith(".js"):
            content_type = "application/javascript; charset=utf-8"
        elif rel.endswith(".png"):
            content_type = "image/png"
        return static_response(start_response, data, content_type)

    if path == "/health":
        return response(start_response, "200 OK", "ok")

    if path == "/" and method == "GET":
        return response(start_response, "200 OK", home_form())

    if path == "/apply" and method == "POST":
        data = parse_body(environ)
        valid, error = validate_application_form(data)
        if not valid:
            return response(start_response, "400 Bad Request", home_form(error=error, values=data))
        app_id = create_application(data)
        return redirect(start_response, f"/quiz?id={app_id}")

    if path == "/quiz" and method == "GET":
        params = query_params(environ)
        raw_id = params.get("id", "")
        if not raw_id.isdigit():
            return response(start_response, "400 Bad Request", quiz_page(0, error="Invalid application id."))
        app_id = int(raw_id)
        row = get_application(app_id)
        if row is None:
            return response(start_response, "404 Not Found", status_page(None))
        if row["status"] != "quiz_pending":
            return redirect(start_response, f"/status?id={app_id}")
        return response(start_response, "200 OK", quiz_page(app_id))

    if path == "/quiz" and method == "POST":
        data = parse_body(environ)
        raw_id = data.get("id", "")
        if not raw_id.isdigit():
            return response(start_response, "400 Bad Request", quiz_page(0, error="Invalid application id."))

        app_id = int(raw_id)
        row = get_application(app_id)
        if row is None:
            return response(start_response, "404 Not Found", status_page(None))
        if row["status"] != "quiz_pending":
            return redirect(start_response, f"/status?id={app_id}")

        score = score_quiz(data)
        total = len(QUIZ_QUESTIONS)
        passed = score >= MIN_PASS_SCORE
        set_quiz_result(app_id, score, total, passed)

        if passed:
            send_application_to_telegram(app_id)
        return redirect(start_response, f"/status?id={app_id}")

    if path == "/status" and method == "GET":
        params = query_params(environ)
        raw_id = params.get("id", "")
        if not raw_id.isdigit():
            return response(start_response, "400 Bad Request", status_page(None))
        row = get_application(int(raw_id))
        return response(start_response, "200 OK", status_page(row))

    return response(
        start_response,
        "404 Not Found",
        html_page("Not found", '<div class="panel"><div class="error">Page not found.</div></div>'),
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    init_db()

    polling = threading.Thread(target=telegram_polling_loop, daemon=True)
    polling.start()

    logging.info("Starting web server on %s:%s", HOST, PORT)
    with make_server(HOST, PORT, app) as httpd:
        httpd.serve_forever()
