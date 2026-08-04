.DEFAULT_GOAL := help
.PHONY: help install lock test test-matrix lint format check record run clean

# Everything runs through `uv run`, which syncs the environment from
# pyproject.toml + uv.lock first, so no target needs to depend on an install
# step. The dev dependency group is synced by default.
UV := uv run

# The dev default is pinned to the oldest supported Python (see .python-version)
# so a 3.10+ only feature cannot sneak past locally. test-matrix covers the top
# of the range.
NEWEST := 3.13

help:  ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk -F':.*?## ' '{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## Sync the environment from uv.lock
	uv sync

lock:  ## Re-resolve dependencies and update uv.lock
	uv lock

test:  ## Run the test suite (replays VCR cassettes, no network)
	VCR_RECORD_MODE=none $(UV) pytest -q

test-matrix:  ## Run the suite on the oldest and newest supported Python
	VCR_RECORD_MODE=none uv run --python 3.9 pytest -q
	VCR_RECORD_MODE=none uv run --python $(NEWEST) pytest -q

lint:  ## Lint with ruff and type-check with ty
	$(UV) ruff check .
	$(UV) ruff format --check .
	$(UV) ty check

format:  ## Autoformat and apply safe lint fixes
	$(UV) ruff format .
	$(UV) ruff check --fix .

check: lint test  ## Everything CI should run

record:  ## Re-record VCR cassettes against the live service
	@echo "Deleting cassettes and hitting the real endpoint..."
	rm -f tests/cassettes/*.yaml
	$(UV) pytest -q

run:  ## Print current service status
	$(UV) observatorio

clean:  ## Remove build and cache artefacts
	rm -rf build dist .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name '*.egg-info' -prune -exec rm -rf {} +
