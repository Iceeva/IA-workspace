.PHONY: up down test test-backend test-front seed migrate

up:            ## pile complète (postgres, redis, api, worker, front)
	docker compose up --build

down:
	docker compose down

migrate:       ## applique les migrations
	cd backend && alembic upgrade head

seed:          ## compte de démonstration
	cd backend && python seed.py

test: test-backend test-front

test-backend:
	cd backend && pytest -q

test-front:
	cd frontend && npm test -- --watch=false
