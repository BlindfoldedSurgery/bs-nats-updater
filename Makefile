.PHONY: check
check: lint test

.PHONY: lint
lint:
	uv run ruff format src/
	uv run ruff check --fix --show-fixes src/
	uv run mypy src/

.PHONY: pre-commit
pre-commit:
	pre-commit install --hook-type commit-msg

.PHONY: test
test:
	uv run pytest src/
