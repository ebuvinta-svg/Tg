Improved Telegram Bot
=====================

Quick start
-----------

1. Copy `.env.example` to `.env` and set `BOT_TOKEN`.
2. Install deps:
   - `make install`
3. Run:
   - `make dev` (debug logging) or `make run`

Docker
------

Build and run:

```
make docker-build
make docker-run
```

Features
--------
- Structured app: `app/` with config, logging, middlewares, handlers
- Robust logging and rate limiting
- Basic commands: /start, /help, /ping, /echo, /admin
- Syntax check: `make test`
Improved Telegram Bot
=====================

Quick start
-----------

1. Copy `.env.example` to `.env` and set `BOT_TOKEN`.
2. Install deps:
   - `make install`
3. Run:
   - `make dev` (debug logging) or `make run`

Docker
------

Build and run:

```
make docker-build
make docker-run
```

Features
--------
- Structured app: `app/` with config, logging, middlewares, handlers
- Robust logging and rate limiting
- Basic commands: /start, /help, /ping, /echo, /admin
- Syntax check: `make test`
