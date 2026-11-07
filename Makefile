.PHONY: up down

up:
	cp -n .env.example .env || true
	docker compose up -d

down:
	docker compose down
