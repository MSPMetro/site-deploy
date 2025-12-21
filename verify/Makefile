.PHONY: setup run

PY ?= python3
VENV := .venv
PYBIN := $(VENV)/bin/python

setup:
	$(PY) -m venv $(VENV)
	$(PYBIN) -m pip install --upgrade pip
	$(PYBIN) -m pip install -r requirements.txt

run:
	$(PYBIN) -m uvicorn app:app --host 127.0.0.1 --port 8000

