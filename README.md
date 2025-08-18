Improved Telegram Bot
=====================

Quick start
-----------

1. Copy `.env.example` to `.env` and set `BOT_TOKEN`. Optionally set `ADMINS=123,456`.
2. Install deps: `make install`
3. Run:
   - `make dev` (debug logging) or `make run`

Features
--------
- Structured app: `app/` with config, logging, middlewares, handlers
- Robust logging and rate limiting with user notice
- Commands: /start, /help, /ping, /echo, /admin, /id, /stats, /broadcast (admins)
- Runtime stats: uptime, unique users, total messages
- Syntax check: `make test`
 
Group management
----------------
- `/settings` — показать настройки чата
- `/welcome on|off [--pin] [текст]` — приветствие новых участников
- `/rules <текст>` — задать правила; `/getrules` — показать
- `/slowmode <сек>` — ограничение частоты сообщений
- `/warn` — предупредить (в ответ на сообщение)
- `/mute [минуты]` — временно ограничить отправку сообщений (в ответ)
- `/ban` — бан пользователя (в ответ)
- `/pin` — закрепить сообщение (в ответ)
