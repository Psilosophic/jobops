.PHONY: up down logs migrate seed test revision

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

migrate:
	docker compose exec api alembic upgrade head

revision:
	docker compose exec api alembic revision --autogenerate -m "$(m)"

seed:
	docker compose exec api python -m app.seeds

test:
	cd backend && python -m pytest -q
