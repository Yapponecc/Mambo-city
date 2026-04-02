# Staff Application Website + Telegram Moderation Bot

This project gives you:
- Web form for player applications.
- Mandatory mini-test after form submission (rules check).
- Telegram moderation with inline buttons (`Approve` / `Reject`).
- SQLite storage for all applications and decisions.

No external Python dependencies are required.

## 1) Configure environment

Create `.env` from `.env.example` and fill values:
- `HOST`
- `PORT`
- `DB_PATH`
- `APP_TITLE`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ADMIN_CHAT_ID`
- `PUBLIC_BASE_URL` (optional)

You can also set these vars in hosting panel environment settings.

Notes:
- `TELEGRAM_ADMIN_CHAT_ID` can be a private user chat id or a group chat id.
- If Telegram env vars are empty, web works, but Telegram moderation is disabled.

## 2) Run

```bash
python app.py
```

Windows note:
- If project is inside OneDrive and SQLite gives `disk I/O error`,
  set `DB_PATH` to a normal writable path (for example `C:\\temp\\applications.db`).

Default URL:
- `http://YOUR_HOST:8080/`

Health endpoint:
- `GET /health`

## 3) Player flow

1. Player opens `/` and fills application form.
2. Player must pass mini-test at `/quiz`.
3. If passed, application status becomes `pending_review` and is sent to Telegram.
4. Admin presses `Approve` or `Reject` in Telegram.
5. Player status page is available via `/status?id=<application_id>`.

## 4) Quiz logic

- Questions are in `app.py` (`QUIZ_QUESTIONS`).
- Pass score: `MIN_PASS_SCORE` (currently 4/5).
- You can edit both values directly in `app.py`.

## 5) Important files

- `app.py` - web server + bot logic.
- `applications.db` - sqlite database (created automatically).
- `.env.example` - sample env values.
