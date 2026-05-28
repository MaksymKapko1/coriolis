include .env
export

.PHONY: run db-up db-down clean

run:
	.venv/bin/python -m uvicorn app.main:app --reload --port 8000

db-up:
	docker-compose up -d postgres

db-down:
	docker-compose down

db-logs:
	docker-compose logs -f postgres

lint:
	uv run ruff check .

format:
	uv run ruff check . --fix
	uv run ruff format .

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +

db-shell:
	PGPASSWORD="$(DB_PASS)" psql \
		-h "$(DB_HOST)" \
		-p "$(DB_PORT)" \
		-U "$(DB_USER)" \
		-d "$(DB_NAME)"