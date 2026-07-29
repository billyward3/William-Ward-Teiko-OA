.PHONY: setup pipeline dashboard test lint format

# Installs into the active environment. Locally that should be a virtualenv;
# in a Codespace the container's Python is fine.
setup:
	python -m pip install --upgrade pip
	python -m pip install -e ".[dev]"

# The whole pipeline, start to finish, with no manual intervention.
# Grows as later parts land; today it initializes the database and loads it.
pipeline:
	python load_data.py

dashboard:
	@echo "make dashboard: not implemented yet, lands with the API."
	@exit 1

test:
	python -m pytest

lint:
	python -m ruff check .
	python -m ruff format --check .
	python -m mypy

format:
	python -m ruff format .
	python -m ruff check --fix .
