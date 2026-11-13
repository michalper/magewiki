.PHONY: up up-local-ai down

up:
	cp -n .env.example .env || true
	docker compose up -d

# Adds a bundled Ollama service (profile local-ai) -- see README's "Running
# fully local" section. Still needs `ollama pull llama3.1`/`ollama pull
# bge-m3` once, and OLLAMA_BASE_URL=http://ollama:11434 in .env.
up-local-ai:
	cp -n .env.example .env || true
	docker compose --profile local-ai up -d

down:
	docker compose down
