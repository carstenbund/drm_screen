# Makefile for drm-screen — PyPI build & publish helper.
#
# Pure-Python package, so (unlike drm-display) there is no C library to compile;
# these targets wrap the standard build/twine workflow.
#
# Requires:  pip install build twine
#
# Targets:
#   make build         - build sdist + wheel into dist/
#   make check         - twine check the built artifacts
#   make publish-test  - upload to TestPyPI
#   make publish       - upload to PyPI
#   make clean         - remove build artifacts
#   make info          - show package name + version

# An interpreter that actually has `build` and `twine`: the stack venv first,
# then a local one, then system python3.  These are dev tools, so where they
# live varies by machine -- `make PY=/path/to/python` overrides.
VENVS := ../.venv/bin/python3 .venv/bin/python3
PY ?= $(firstword $(wildcard $(VENVS)) python3)

# "No module named build" is a poor error for a missing tool, so say it plainly.
TOOLS = @$(PY) -c "import build, twine" 2>/dev/null || { \
	  echo "$(PY) has neither build nor twine."; \
	  echo "  pip install build twine"; \
	  echo "  or: make PY=/path/to/a/venv/bin/python $@"; \
	  exit 1; }

.PHONY: build check publish publish-test clean info

build: clean
	$(TOOLS)
	$(PY) -m build

check: build
	$(PY) -m twine check dist/*

publish-test: check
	$(PY) -m twine upload --repository testpypi dist/*

publish: check
	$(PY) -m twine upload dist/*

clean:
	rm -rf dist build *.egg-info

info:
	@grep -E '^(name|version)' pyproject.toml
