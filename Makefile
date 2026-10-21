.PHONY: run test lint db-up migrate demo site

run:
	uv run uvicorn app.main:app --reload

test: migrate
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy app

db-up:
	@if [ -z "$$DATABASE_URL" ]; then docker compose up -d --wait db; else echo "Using DATABASE_URL supplied by the environment"; fi

migrate: db-up
	uv run alembic upgrade head

demo: db-up
	uv run alembic upgrade head
	docker compose up -d --build api
	uv run python -m app.demo --base-url http://localhost:8000

site:
	uv run python scripts/build_site.py
