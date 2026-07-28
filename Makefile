.PHONY: setup test lint format

# Installs into the active environment. Locally that should be a virtualenv;
# in a Codespace the container's Python is fine.
setup:
	python -m pip install --upgrade pip
	python -m pip install -e ".[dev]"

test:
	python -m pytest

lint:
	python -m ruff check .
	python -m ruff format --check .
	python -m mypy

format:
	python -m ruff format .
	python -m ruff check --fix .
