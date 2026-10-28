.PHONY: test venv clean regen-fixtures

VENV ?= .venv
PYTHON ?= python3
# The minor version of PYTHON. The venv is built for it, so a different
# PYTHON (a CI matrix entry, or OrbySystems pinning the 3.12 its app runs
# parsers on) rebuilds the venv rather than reusing one made from another.
PYVER := $(shell $(PYTHON) -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>/dev/null)
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

venv: $(VENV)/.stamp-$(PYVER)

$(VENV)/.stamp-$(PYVER): requirements-test.txt
	@test -n "$(PYVER)" || { echo "$(PYTHON) is not a Python interpreter: run make PYTHON=<python3.x>" >&2; exit 1; }
	$(PYTHON) -m venv --clear "$(VENV)"
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements-test.txt
	"$(PY)" -c "from pathlib import Path; import sys; Path(sys.argv[1]).touch()" "$@"

# Rebuild every committed synthetic fixture from its generator.
regen-fixtures: venv
	@for g in tests/generators/gen-*.py; do echo "=> $$g"; $(PY) "$$g"; done

clean:
	rm -rf $(VENV) .pytest_cache tests/**/__pycache__
