PY := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)
PIP := $(shell [ -x .venv/bin/pip ] && echo .venv/bin/pip || echo pip3)

.PHONY: install run dev test

install:
	python3 -m venv .venv || true
	[ -x .venv/bin/pip ] && .venv/bin/pip install -r requirements.txt || pip3 install --user --break-system-packages -r requirements.txt

run:
	$(PY) -m app.main

dev:
	BOT_LOG_LEVEL=DEBUG $(PY) -m app.main

test:
	$(PY) -m compileall -q app
	@echo "Syntax OK"
