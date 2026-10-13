.PHONY: up down test logs
up:
	docker compose up --build -d
down:
	docker compose down
test:
	docker compose exec api python -m pytest -q
logs:
	docker compose logs --tail=100 api worker web
