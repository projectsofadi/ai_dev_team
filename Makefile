.PHONY: install install-core install-server install-cli dev test lint typecheck clean

install: install-core install-server install-cli

install-core:
	cd packages/core && pip install -e ".[dev]"

install-server:
	cd packages/server && npm install

install-cli:
	cd packages/cli && npm install

dev-server:
	cd packages/server && npm run dev

dev-cli:
	cd packages/cli && npm run dev

test:
	cd packages/core && python -m pytest tests/ -v --cov=src/ai_dev_team

test-unit:
	cd packages/core && python -m pytest tests/unit/ -v

test-integration:
	cd packages/core && python -m pytest tests/integration/ -v

lint:
	cd packages/core && ruff check src/ tests/
	cd packages/server && npm run lint 2>/dev/null || true
	cd packages/cli && npm run typecheck 2>/dev/null || true

typecheck:
	cd packages/core && mypy src/ai_dev_team/
	cd packages/server && npm run typecheck
	cd packages/cli && npm run typecheck

format:
	cd packages/core && ruff format src/ tests/

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf packages/server/dist packages/cli/dist
	rm -rf packages/server/node_modules packages/cli/node_modules
	rm -rf .pytest_cache .mypy_cache .coverage htmlcov

docker-up:
	docker compose up -d

docker-down:
	docker compose down
