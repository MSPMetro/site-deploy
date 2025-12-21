.PHONY: help setup lint build cable clean check-id

SHELL := /bin/bash
PY ?= python3
VENV := .venv
PYBIN := $(VENV)/bin/python

help:
	@echo "Targets:"
	@echo "  make setup"
	@echo "  make lint"
	@echo "  make build"
	@echo "  make cable ID=MSPM-CBL-YYYY-MM-DD-###"
	@echo "  make clean"

$(PYBIN):
	$(PY) -m venv $(VENV)
	$(PYBIN) -m pip install --upgrade pip
	$(PYBIN) -m pip install -r requirements.txt

setup: $(PYBIN)

lint: $(PYBIN)
	$(PYBIN) tools/lint_cable.py content

build: $(PYBIN)
	$(PYBIN) tools/build_cable.py --all

check-id:
	@if [[ -z "$(ID)" ]]; then echo "ERROR: ID is required (e.g. make cable ID=MSPM-CBL-...)"; exit 2; fi
	@if ! [[ "$(ID)" =~ ^MSPM-CBL-[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{3}$$ ]]; then echo "ERROR: invalid ID: $(ID)"; exit 2; fi

# Build a single cable from the authoritative content path convention:
#   content/YYYY/MM/DD/mspm-cbl-yyyy-mm-dd-###.md
cable: $(PYBIN) check-id
	@ID_LOWER="$$(echo "$(ID)" | tr '[:upper:]' '[:lower:]')"; \
	DATE="$${ID_LOWER#mspm-cbl-}"; DATE="$${DATE%-*}"; \
	Y="$${DATE%%-*}"; REST="$${DATE#*-}"; M="$${REST%%-*}"; D="$${REST#*-}"; \
	MD="content/$${Y}/$${M}/$${D}/$${ID_LOWER}.md"; \
	if [[ ! -f "$$MD" ]]; then echo "ERROR: missing source: $$MD" >&2; exit 2; fi; \
	$(PYBIN) tools/build_cable.py --in "$$MD"

clean:
	rm -rf build/html build/pdf build/aztec build/manifest
