.DEFAULT_GOAL := help
.PHONY: help install hooks lock test coverage test-matrix lint format check dist record run clean

# Everything runs through `uv run`, which syncs the environment from
# pyproject.toml + uv.lock first, so no target needs to depend on an install
# step. The dev dependency group is synced by default.
UV := uv run

# The dev default is pinned to the newest supported Python (see .python-version)
# for day-to-day local work. test-matrix still covers the bottom of the range
# so too-new syntax is caught before CI.
NEWEST := 3.14

help:  ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk -F':.*?## ' '{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## Sync the environment from uv.lock
	uv sync

hooks:  ## Install the git pre-commit hook (do this once after cloning)
	$(UV) pre-commit install

lock:  ## Re-resolve dependencies and update uv.lock
	uv lock

test:  ## Run the test suite (replays VCR cassettes, no network)
	VCR_RECORD_MODE=none $(UV) pytest -q

coverage:  ## Run tests with coverage and write coverage.xml
	VCR_RECORD_MODE=none $(UV) pytest -q --cov --cov-report=term-missing --cov-report=xml

test-matrix:  ## Run the suite on the oldest and newest supported Python
	VCR_RECORD_MODE=none uv run --python 3.12 pytest -q
	VCR_RECORD_MODE=none uv run --python $(NEWEST) pytest -q

# Runs the pre-commit hooks rather than calling ruff and ty directly, so this,
# the git hook and CI are all the same list of checks -- there is nowhere for
# them to drift apart. The hooks fix what they safely can and then fail, so this
# target can leave the tree modified; re-run it to confirm what is left.
lint:  ## Run every check the git hook and CI run
	$(UV) pre-commit run --all-files

format:  ## Autoformat and apply safe lint fixes
	$(UV) ruff format .
	$(UV) ruff check --fix .

check: lint test  ## Everything CI should run

dist:  ## Build the sdist and wheel, and check what PyPI would reject
	rm -rf dist
	uv build
	uvx twine check --strict dist/*

record:  ## Re-record VCR cassettes against the live service
	@echo "Deleting cassettes and hitting the real endpoint..."
	rm -f tests/cassettes/*.yaml
	$(UV) pytest -q

run:  ## Print current service status
	$(UV) observatorio

clean:  ## Remove build and cache artefacts
	rm -rf build dist .pytest_cache .ruff_cache .coverage coverage.xml
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name '*.egg-info' -prune -exec rm -rf {} +
