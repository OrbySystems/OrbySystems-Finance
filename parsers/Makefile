.PHONY: test venv clean regen-fixtures

VENV ?= .venv
PYTHON ?= python3
ifeq ($(OS),Windows_NT)
PY   := $(VENV)/Scripts/python.exe
else
PY   := $(VENV)/bin/python
endif
PIP  := "$(PY)" -m pip

# Standalone parser test suite. Provisions a local venv on first run
# (pdfplumber, openpyxl, pytest, pillow), then runs pytest over tests/.
test: venv
	"$(PY)" -m pytest

venv: $(VENV)/.stamp

$(VENV)/.stamp: requirements-test.txt
	$(PYTHON) -m venv "$(VENV)"
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements-test.txt
	"$(PY)" -c "from pathlib import Path; import sys; Path(sys.argv[1]).touch()" "$@"

# Rebuild every committed synthetic fixture from its generator.
regen-fixtures: venv
	@for g in tests/generators/gen-*.py; do echo "=> $$g"; $(PY) "$$g"; done

clean:
	rm -rf $(VENV) .pytest_cache tests/**/__pycache__
