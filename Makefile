.PHONY: setup seed mcp mcp-http fmt fmt-check lint typecheck test check inspector

setup:
	uv sync --all-groups

seed:
	uv run csa-seed --db var/citizen.db --force

mcp:
	uv run csa-mcp

mcp-http:
	uv run csa-mcp --transport streamable-http

fmt:
	uv run ruff format .

fmt-check:
	uv run ruff format --check .

lint:
	uv run ruff check .

typecheck:
	uv run mypy

test:
	uv run pytest

check: fmt-check lint typecheck test

inspector:
	npx @modelcontextprotocol/inspector uv run csa-mcp
