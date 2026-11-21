.PHONY: help setup setup-all doctor test lint fmt diagram

help:            ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

setup:           ## create .venv and install core + dev deps
	uv sync --extra dev
	@test -f .env || (cp .env.example .env && chmod 600 .env && echo "created .env — fill in keys")

setup-all:       ## install every optional extra (gliner pulls torch: large)
	uv sync --all-extras

doctor:          ## check env keys (presence only), config, folders
	uv run cf doctor

test:            ## run tests
	uv run pytest -q

lint:            ## ruff check
	uv run ruff check src tests

fmt:             ## ruff format
	uv run ruff format src tests

diagram:         ## render docs/architecture.svg -> docs/architecture.png
	rsvg-convert -w 1600 docs/architecture.svg -o docs/architecture.png
