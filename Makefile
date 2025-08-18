PYTHON ?= python3
PIP ?= pip3

.PHONY: install run dev test docker-build docker-run

install:
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

run:
	$(PYTHON) -m app.main

dev:
	BOT_LOG_LEVEL=DEBUG $(PYTHON) -m app.main

test:
	$(PYTHON) -m compileall -q app
	@echo "Syntax OK"

docker-build:
	docker build -t improved-bot:latest .

docker-run:
	docker run --rm -it --env-file .env improved-bot:latest
