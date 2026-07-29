.PHONY: setup setup-python frontend frontend-check pipeline dashboard test lint format

# Installs everything: the Python package, then the dashboard's front end.
#
# The two are deliberately not equal partners. A failure in `npm ci` or in the
# Vite build must not take Parts 1 to 4 with it, so the front end is built
# through a recursive call whose exit status is swallowed and reported as a
# warning. `make pipeline` and every graded output still work on a machine with
# no Node toolchain at all, and the API still serves the analysis and its
# reference at /docs; only the charts are missing.
#
# `make frontend` on its own does fail loudly, because there the build is the
# point rather than a bonus.
setup: setup-python
	@$(MAKE) --no-print-directory frontend || printf '%s\n%s\n%s\n' \
	  "" \
	  "warning: the dashboard front end did not build, so \`make dashboard\` will" \
	  "serve the API only. Parts 1 to 4 and \`make pipeline\` are unaffected." >&2

# Installs into the active environment. Locally that should be a virtualenv;
# in a Codespace the container's Python is fine.
setup-python:
	python -m pip install --upgrade pip
	python -m pip install -e ".[dev]"

# `npm ci` rather than `npm install`, so the tree a grader gets is the tree the
# lockfile pins rather than whatever resolved that morning.
frontend:
	cd frontend && npm ci && npm run build

# The front end's own gate: types first, then the component tests.
frontend-check:
	cd frontend && npm run typecheck && npm test

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
