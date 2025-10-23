.PHONY: check
check: lint test

.PHONY: lint
lint:
	uv run ruff format
	uv run ruff check --fix --show-fixes
	uv run mypy src/ tests/

.PHONY: pre-commit
pre-commit:
	pre-commit install --hook-type commit-msg

.PHONY: test
test:
	uv run pytest
