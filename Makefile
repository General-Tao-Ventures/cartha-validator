UV ?= uv

.PHONY: sync lint format typecheck test

sync:
	$(UV) sync

lint:
	$(UV) run ruff check .

format:
	$(UV) run ruff format .

typecheck:
	$(UV) run mypy --config-file mypy.ini packages

test: lint typecheck
	$(UV) run pytest
