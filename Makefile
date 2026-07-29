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

# One process on one port: FastAPI serves the analysis under /api and the built
# frontend, if there is one, at the root. Binds every interface rather than
# loopback, because a Codespace forwards the port from outside the container.
#
# Needs the database, which `make pipeline` builds.
dashboard:
	python -m cellcount.api

test:
	python -m pytest

lint:
	python -m ruff check .
	python -m ruff format --check .
	python -m mypy

format:
	python -m ruff format .
	python -m ruff check --fix .
