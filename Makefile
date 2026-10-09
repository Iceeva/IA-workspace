.PHONY: up down test test-backend test-bridge test-front seed migrate bridge

up:            ## pile complète (postgres, redis, api, worker, front)
	docker compose up --build

down:
	docker compose down

migrate:       ## applique les migrations
	cd backend && alembic upgrade head

seed:          ## compte de démonstration
	cd backend && python seed.py

test: test-backend test-bridge test-front

test-backend:
	cd backend && pytest -q

test-front:
	cd frontend && npm test -- --watch=false

test-bridge:
	PYTHONPATH=backend python bridge/tests/test_bridge.py
	PYTHONPATH=backend:bridge python bridge/tests/test_pull.py

bridge:        ## Local Bridge (modèles locaux pour l'app web) — voir docs/PLATFORM.md
	PYTHONPATH=backend python -m aiw_bridge --origin http://localhost:4200 --models-dir ~/models
