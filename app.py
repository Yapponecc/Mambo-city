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
APP_TITLE = os.getenv("APP_TITLE", "Mambo City | Заявка в команду")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "").strip()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip()
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

MIN_PASS_SCORE = 5
RESOLVED_DB_PATH = ""

INLINE_CSS = """
:root {
  --bg-deep: #090f1a;
  --bg-mid: #101b2b;
  --bg-soft: #152a41;
  --panel: rgba(16, 29, 45, 0.72);
  --panel-border: rgba(255, 255, 255, 0.1);
  --text: #f2f7ff;
  --text-muted: #b8c9dd;
  --accent: #ffd166;
  --accent-2: #4ed6c8;
  --danger: #ff6b6b;
  --ok: #57cc99;
  --field-bg: rgba(8, 16, 28, 0.62);
  --field-border: rgba(150, 182, 219, 0.35);
  --shadow: 0 18px 45px rgba(0, 0, 0, 0.35);
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  color: var(--text);
  font-family: "Segoe UI", "Trebuchet MS", sans-serif;
  min-height: 100vh;
  padding: 26px;
  background:
    radial-gradient(circle at 18% 8%, #2f4f75 0%, transparent 34%),
    radial-gradient(circle at 86% 14%, #2b6f77 0%, transparent 30%),
    radial-gradient(circle at 48% 88%, #493060 0%, transparent 28%),
    linear-gradient(160deg, var(--bg-soft) 0%, var(--bg-mid) 44%, var(--bg-deep) 100%);
}

.wrap {
  max-width: 980px;
  margin: 0 auto;
}

.hero {
  margin-bottom: 20px;
  background: linear-gradient(120deg, rgba(255, 209, 102, 0.15), rgba(78, 214, 200, 0.11));
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 18px;
  padding: 18px 20px;
  box-shadow: var(--shadow);
  backdrop-filter: blur(4px);
}

.hero h1 {
  margin: 0 0 6px;
  font-size: 34px;
  letter-spacing: 0.25px;
}

.hero p {
  margin: 0;
  color: #d4e4f5;
  line-height: 1.45;
}

.steps {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  background: var(--panel);
  border: 1px solid var(--panel-border);
  backdrop-filter: blur(5px);
}

.step {
  border-radius: 12px;
  padding: 12px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.step.active {
  background: linear-gradient(145deg, rgba(255, 209, 102, 0.2), rgba(78, 214, 200, 0.15));
  border-color: rgba(255, 209, 102, 0.45);
}

.step-number {
  display: inline-flex;
  width: 26px;
  height: 26px;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  font-weight: 800;
  color: #132236;
  margin-right: 7px;
  background: linear-gradient(135deg, var(--accent), #ffb347);
}

.step-title {
  font-weight: 800;
  font-size: 14px;
  color: #f6fbff;
}

.step-sub {
  margin-top: 6px;
  color: #c7d8eb;
  font-size: 13px;
  line-height: 1.35;
}

.panel {
  background: var(--panel);
  border: 1px solid var(--panel-border);
  border-radius: 16px;
  padding: 22px;
  box-shadow: var(--shadow);
  margin-bottom: 16px;
  backdrop-filter: blur(5px);
}

.panel h2,
.panel h3 {
  color: #f7fbff;
}

.grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

label {
  font-size: 12px;
  font-weight: 700;
  color: #bdd1e6;
  display: block;
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.7px;
}

input,
textarea {
  width: 100%;
  padding: 11px 12px;
  border-radius: 10px;
  border: 1px solid var(--field-border);
  font-size: 14px;
  font-family: inherit;
  color: #f2f7ff;
  background: var(--field-bg);
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

input:focus,
textarea:focus {
  outline: none;
  border-color: rgba(255, 209, 102, 0.9);
  box-shadow: 0 0 0 3px rgba(255, 209, 102, 0.18);
}

.field-help {
  margin-top: 6px;
  font-size: 12px;
  color: #9eb3c9;
}

textarea {
  min-height: 120px;
  resize: vertical;
}

.full {
  grid-column: 1 / -1;
}

.rules {
  margin: 12px 0 0;
  padding-left: 18px;
  color: #c5d6ea;
  line-height: 1.5;
}

.btn {
  background: linear-gradient(135deg, var(--accent), #ffb347);
  color: #1e1500;
  border: 0;
  padding: 11px 16px;
  border-radius: 11px;
  font-size: 14px;
  font-weight: 800;
  cursor: pointer;
  margin-top: 8px;
  transition: transform 0.15s ease, filter 0.15s ease;
}

.btn.big {
  width: 100%;
  padding: 14px 18px;
  font-size: 16px;
  border-radius: 12px;
}

.btn:hover {
  filter: brightness(1.02);
  transform: translateY(-1px);
}

.btn:active {
  transform: translateY(0);
}

.muted {
  color: var(--text-muted);
}

.error {
  border-left: 4px solid var(--danger);
  background: rgba(255, 107, 107, 0.16);
  color: #ffe3e3;
  padding: 10px 12px;
  border-radius: 8px;
  margin-bottom: 12px;
}

.ok {
  border-left: 4px solid var(--ok);
  background: rgba(87, 204, 153, 0.18);
  color: #eafff3;
  padding: 10px 12px;
  border-radius: 8px;
  margin-bottom: 12px;
}

.status-pill {
  display: inline-block;
  padding: 5px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #fff;
  background: #607388;
}

.status-pill.pending_review {
  background: #d79b22;
  color: #1f1400;
}

.status-pill.approved {
  background: #1fa95f;
}

.status-pill.rejected,
.status-pill.quiz_failed {
  background: #d64545;
}

.hint {
  background: rgba(78, 214, 200, 0.13);
  border: 1px solid rgba(78, 214, 200, 0.36);
  color: #dcfffa;
  padding: 10px 12px;
  border-radius: 10px;
  margin-top: 10px;
  line-height: 1.45;
}

@media (max-width: 760px) {
  body {
    padding: 16px;
  }

  .steps {
    grid-template-columns: 1fr;
  }

  .grid {
    grid-template-columns: 1fr;
  }

  .hero h1 {
    font-size: 27px;
  }

  .panel {
    padding: 16px;
  }
}
"""

QUIZ_QUESTIONS = [
    {
        "id": "q1",
        "question": "Можно ли использовать читы/макросы/xray на сервере?",
        "options": [
            ("a", "Нет, любые читы и нечестное преимущество запрещены."),
            ("b", "Можно, если редко."),
            ("c", "Можно, если никто не увидит."),
        ],
        "correct": "a",
    },
    {
        "id": "q2",
        "question": "Как нужно вести себя в чате?",
        "options": [
            ("a", "Спам и оскорбления допустимы."),
            ("b", "Общаться уважительно, без травли и оскорблений."),
            ("c", "Уважительно должны общаться только админы."),
        ],
        "correct": "b",
    },
    {
        "id": "q3",
        "question": "Можно ли ломать или воровать вещи/постройки других игроков?",
        "options": [
            ("a", "Нет, гриф и воровство запрещены."),
            ("b", "Да, если получится."),
            ("c", "Да, только в приватах."),
        ],
        "correct": "a",
    },
    {
        "id": "q4",
        "question": "Можно ли рекламировать другие проекты/сервера в чате?",
        "options": [
            ("a", "Да, любая реклама приветствуется."),
            ("b", "Да, если сначала спросить игроков."),
            ("c", "Нет, без согласования с администрацией нельзя."),
        ],
        "correct": "c",
    },
    {
        "id": "q5",
        "question": "Вы нашли баг/эксплойт. Что нужно сделать?",
        "options": [
            ("a", "Использовать в свою пользу."),
            ("b", "Сообщить администрации/модерации."),
            ("c", "Продать информацию другим игрокам."),
        ],
        "correct": "b",
    },
    {
        "id": "q6",
        "question": "На каком расстоянии от спавна можно начинать строительство базы?",
        "options": [
            ("a", "Только от 1000 блоков от спавна."),
            ("b", "Можно прямо у спавна."),
            ("c", "Достаточно 100 блоков от спавна."),
        ],
        "correct": "a",
    },
]

RULES_SUMMARY = [
    "Запрещены читы, xray, макросы, дюпы и любые нечестные преимущества.",
    "Соблюдайте уважительное общение с игроками и администрацией.",
    "Запрещены гриф, кража и умышленная порча чужих построек.",
    "Строить базу разрешено только на расстоянии от 1000 блоков от спавна.",
    "Реклама сторонних проектов запрещена без согласования.",
    "Найденные баги/эксплойты нужно сообщать администрации, а не использовать.",
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
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(title)}</title>
  <style>{INLINE_CSS}</style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <h1>{escape(APP_TITLE)}</h1>
      <p>Заполни анкету → пройди мини‑тест по правилам → получи решение в Telegram.</p>
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
            <div><span class="step-number">1</span><span class="step-title">Заполни анкету</span></div>
            <div class="step-sub">Укажи ник, контакт и мотивацию.</div>
          </div>
          <div class="step">
            <div><span class="step-number">2</span><span class="step-title">Пройди мини‑тест</span></div>
            <div class="step-sub">6 вопросов по основным правилам сервера.</div>
          </div>
          <div class="step">
            <div><span class="step-number">3</span><span class="step-title">Проверка в Telegram</span></div>
            <div class="step-sub">Админ примет или отклонит заявку кнопкой.</div>
          </div>
        </div>

        <div class="panel">
          {error_block}
          <h2 style="margin-top:0">Анкета на вступление в команду</h2>
          <p class="muted">Заполни все поля и нажми большую кнопку внизу, чтобы перейти к мини‑тесту.</p>
          <div class="grid">
            <div>
              <label>Ник в Minecraft</label>
              <input name="minecraft_nick" form="app-form" placeholder="Пример: Yapponecc" value="{escape(values.get("minecraft_nick", ""))}" required />
              <div class="field-help">Укажи ник точно как в игре.</div>
            </div>
            <div>
              <label>Возраст</label>
              <input name="age" type="number" min="10" max="99" form="app-form" value="{escape(values.get("age", ""))}" required />
              <div class="field-help">Допустимый диапазон: 10-99.</div>
            </div>
            <div>
              <label>Контакт в Telegram</label>
              <input name="telegram_contact" form="app-form" placeholder="@username или id" value="{escape(values.get("telegram_contact", ""))}" required />
              <div class="field-help">Нужен для обратной связи после проверки.</div>
            </div>
            <div>
              <label>Часовой пояс</label>
              <input name="timezone_label" form="app-form" placeholder="Europe/Moscow" value="{escape(values.get("timezone_label", ""))}" />
              <div class="field-help">Необязательно, но удобно для связи.</div>
            </div>
            <div class="full">
              <label>Игровой опыт / активность</label>
              <textarea name="playtime" form="app-form" required>{escape(values.get("playtime", ""))}</textarea>
            </div>
            <div class="full">
              <label>Почему ты хочешь в команду проекта?</label>
              <textarea name="motivation" form="app-form" required>{escape(values.get("motivation", ""))}</textarea>
            </div>
            <div class="full">
              <label><input style="width:auto" type="checkbox" name="agree_rules" form="app-form" value="yes" {"checked" if values.get("agree_rules") else ""} /> Я прочитал основные правила, включая правило строительства только от 1000 блоков от спавна, и согласен их соблюдать.</label>
            </div>
          </div>
          <ul class="rules">{rules_html}</ul>
          <div class="hint">После нажатия кнопки откроется мини‑тест по правилам. Без него заявка не отправляется в проверку.</div>
          <form id="app-form" method="post" action="/apply">
            <button class="btn big" type="submit">Перейти к мини‑тесту -></button>
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
            f'<div class="panel"><h3 style="margin-top:0">Вопрос {index}. {escape(q["question"])}</h3>'
            f'{"".join(options)}</div>'
        )
        question_blocks.append(block)

    body = (
        f'<div class="panel steps">'
        f'<div class="step"><div><span class="step-number">1</span><span class="step-title">Анкета отправлена</span></div>'
        f'<div class="step-sub">Базовая информация сохранена.</div></div>'
        f'<div class="step active"><div><span class="step-number">2</span><span class="step-title">Мини‑тест</span></div>'
        f'<div class="step-sub">Выбери по одному ответу в каждом вопросе.</div></div>'
        f'<div class="step"><div><span class="step-number">3</span><span class="step-title">Проверка в Telegram</span></div>'
        f'<div class="step-sub">Стартует только при успешном прохождении теста.</div></div></div>'
        f'<div class="panel">{error_block}<h2 style="margin-top:0">Мини‑тест по правилам</h2>'
        f'<p class="muted">Проходной балл: {MIN_PASS_SCORE}/{len(QUIZ_QUESTIONS)}. '
        f'Только прошедшие тест заявки уходят в Telegram на проверку.</p>'
        f'<div class="hint">Внимательно проверь ответы перед отправкой.</div></div>'
        f'<form method="post" action="/quiz"><input type="hidden" name="id" value="{application_id}" />'
        f'{"".join(question_blocks)}'
        f'<div class="panel"><button class="btn big" type="submit">Отправить тест и заявку</button></div></form>'
    )
    return html_page("Мини‑тест", body)


def status_label(status: str) -> str:
    mapping = {
        "quiz_pending": "Ожидает тест",
        "quiz_failed": "Тест не пройден",
        "pending_review": "На проверке",
        "approved": "Одобрено",
        "rejected": "Отклонено",
    }
    return mapping.get(status, status)


def status_page(row: sqlite3.Row | None) -> str:
    if row is None:
        return html_page(
            "Статус",
            '<div class="panel"><div class="error">Заявка не найдена. Проверь ссылку или id.</div></div>',
        )

    status = row["status"]
    score_info = ""
    if row["quiz_score"] is not None and row["quiz_total"] is not None:
        score_info = f'<p><strong>Результат теста:</strong> {row["quiz_score"]}/{row["quiz_total"]}</p>'

    note = ""
    if status == "quiz_failed":
        note = '<div class="error">Мини‑тест не пройден. Обратись к администрации, если нужна повторная попытка.</div>'
    elif status == "pending_review":
        note = '<div class="ok">Тест пройден. Заявка ожидает решения модератора в Telegram.</div>'
    elif status == "approved":
        note = '<div class="ok">Заявка одобрена. Команда проекта свяжется с тобой в Telegram.</div>'
    elif status == "rejected":
        note = '<div class="error">Заявка отклонена модерацией.</div>'

    body = f"""
      <div class="panel">
        <h2 style="margin-top:0">Заявка #{row['id']}</h2>
        <p><strong>Ник Minecraft:</strong> {escape(row['minecraft_nick'])}</p>
        <p><strong>Статус:</strong> <span class="status-pill {escape(status)}">{escape(status_label(status))}</span></p>
        {score_info}
        {note}
        <div class="hint">Сохрани эту ссылку: статус автоматически обновится после решения модерации.</div>
      </div>
    """
    return html_page("Статус заявки", body)


def validate_application_form(data: dict[str, str]) -> tuple[bool, str]:
    required_fields = ["minecraft_nick", "age", "telegram_contact", "playtime", "motivation"]
    field_names = {
        "minecraft_nick": "Ник в Minecraft",
        "age": "Возраст",
        "telegram_contact": "Контакт в Telegram",
        "playtime": "Игровой опыт / активность",
        "motivation": "Почему ты хочешь в команду проекта",
    }
    for field in required_fields:
        if not data.get(field, "").strip():
            return False, f"Поле «{field_names.get(field, field)}» обязательно для заполнения."

    if data.get("agree_rules") != "yes":
        return False, "Подтверди, что ты прочитал правила."

    try:
        age = int(data["age"])
    except ValueError:
        return False, "Возраст должен быть числом."

    if age < 10 or age > 99:
        return False, "Возраст должен быть в диапазоне от 10 до 99."

    if len(data.get("minecraft_nick", "")) > 32:
        return False, "Ник Minecraft слишком длинный."

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
        f"<b>Новая заявка #{row['id']}</b>",
        "",
        f"<b>Ник Minecraft:</b> {escape(row['minecraft_nick'])}",
        f"<b>Возраст:</b> {row['age']}",
        f"<b>Telegram:</b> {escape(row['telegram_contact'])}",
    ]
    if row["timezone_label"]:
        lines.append(f"<b>Часовой пояс:</b> {escape(row['timezone_label'])}")
    lines.extend(
        [
            "",
            "<b>Игровой опыт / активность</b>",
            escape(row["playtime"]),
            "",
            "<b>Мотивация</b>",
            escape(row["motivation"]),
            "",
            f"<b>Тест:</b> {row['quiz_score']}/{row['quiz_total']}",
        ]
    )
    if PUBLIC_BASE_URL:
        lines.append(f"\n<b>Страница статуса:</b> {escape(PUBLIC_BASE_URL)}/status?id={row['id']}")
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
                    {"text": "✅ Одобрить", "callback_data": f"approve:{application_id}"},
                    {"text": "❌ Отклонить", "callback_data": f"reject:{application_id}"},
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
    status = "ОДОБРЕНО" if row["status"] == "approved" else "ОТКЛОНЕНО"
    mod = row["decision_by"] or "неизвестно"
    return (
        f"<b>Заявка #{row['id']} — {status}</b>\n\n"
        f"<b>Ник Minecraft:</b> {escape(row['minecraft_nick'])}\n"
        f"<b>Тест:</b> {row['quiz_score']}/{row['quiz_total']}\n"
        f"<b>Модератор:</b> {escape(mod)}"
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
            {"callback_query_id": callback_id, "text": "Эта кнопка доступна только в админ-чате.", "show_alert": False},
        )
        return

    action, _, raw_id = data.partition(":")
    if action not in {"approve", "reject"} or not raw_id.isdigit():
        telegram_api_call(
            "answerCallbackQuery",
            {"callback_query_id": callback_id, "text": "Некорректное действие.", "show_alert": False},
        )
        return

    app_id = int(raw_id)
    changed = set_decision(app_id, approved=(action == "approve"), moderator=moderator)
    if not changed:
        telegram_api_call(
            "answerCallbackQuery",
            {"callback_query_id": callback_id, "text": "Эта заявка уже была рассмотрена.", "show_alert": False},
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
        {"callback_query_id": callback_id, "text": "Решение сохранено.", "show_alert": False},
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
                html_page("Не найдено", '<div class="panel"><div class="error">Статический файл не найден.</div></div>'),
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
            return response(start_response, "400 Bad Request", quiz_page(0, error="Некорректный id заявки."))
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
            return response(start_response, "400 Bad Request", quiz_page(0, error="Некорректный id заявки."))

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
        html_page("Не найдено", '<div class="panel"><div class="error">Страница не найдена.</div></div>'),
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    init_db()

    polling = threading.Thread(target=telegram_polling_loop, daemon=True)
    polling.start()

    logging.info("Starting web server on %s:%s", HOST, PORT)
    with make_server(HOST, PORT, app) as httpd:
        httpd.serve_forever()
