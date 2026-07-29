.PHONY: setup pipeline dashboard test lint format

# Installs into the active environment. Locally that should be a virtualenv;
# in a Codespace the container's Python is fine.
setup:
	python -m pip install --upgrade pip
	python -m pip install -e ".[dev]"

# The whole pipeline, start to finish, with no manual intervention: creates the
# database, loads cell-count.csv (Part 1), then writes every table, the figure
# and the write-up for Parts 2 to 4 into outputs/.
#
# The load step is the same code `python load_data.py` runs standalone, so the
# two entry points cannot build different databases.
pipeline:
	python -m cellcount.pipeline

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
