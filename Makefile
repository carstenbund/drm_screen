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

PY ?= python3

.PHONY: build check publish publish-test clean info

build: clean
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
