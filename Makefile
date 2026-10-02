API_HEALTH_URL ?= http://localhost:8000/health
API_WAIT_ATTEMPTS ?= 30
API_WAIT_SLEEP ?= 2
QUALITY_PATHS = apps/api/app/core apps/api/app/security apps/api/app/repositories/scoped.py apps/api/app/db/unit_of_work.py tests

install:
	bash scripts/install.sh

dev:
	bash scripts/dev.sh

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

pull-model:
	bash scripts/pull-models.sh mistral

wait-api:
	@echo "Waiting for API health endpoint: $(API_HEALTH_URL)"
	@for i in $$(seq 1 $(API_WAIT_ATTEMPTS)); do \
		if curl -fsS $(API_HEALTH_URL) >/dev/null 2>&1; then \
			echo "API is ready"; \
			exit 0; \
		fi; \
		echo "API not ready yet ($$i/$(API_WAIT_ATTEMPTS))"; \
		sleep $(API_WAIT_SLEEP); \
	done; \
	echo "API did not become ready in time"; \
	exit 1

health:
	curl -s $(API_HEALTH_URL)

smoke-runtime:
	python3 scripts/smoke_knowledge_runtime.py
	python3 scripts/smoke_answer_mode_contract.py
	python3 scripts/smoke_inference_provider_abstraction.py
	python3 scripts/smoke_prompt_guardrail_references.py
	python3 scripts/smoke_assisted_answer_runtime.py
	python3 scripts/smoke_fallback_error_semantics.py
	python3 scripts/smoke_embedding_reference_contract.py
	python3 scripts/smoke_vector_provider_abstraction.py
	python3 scripts/smoke_derived_vector_index_lifecycle.py
	python3 scripts/smoke_hybrid_candidate_merge.py
	python3 scripts/smoke_retrieval_contribution_metrics.py

smoke-sprint-12:
	python3 scripts/smoke_sprint_12_runtime.py

smoke-sprint-13:
	python3 scripts/smoke_sprint_13_runtime.py

smoke-sprint-18-1:
	python3 scripts/smoke_platform_metadata.py

smoke-sprint-18-2:
	python3 scripts/smoke_request_context.py

smoke-sprint-18-3:
	python3 scripts/smoke_tenant_repository_boundary.py

quality-install:
	python3 -m pip install -r apps/api/requirements-dev.txt

quality-test:
	python3 -m pytest

quality-coverage:
	python3 -m pytest --cov=apps/api/app --cov-report=term-missing

quality-lint:
	python3 -m ruff check $(QUALITY_PATHS)

quality-format:
	python3 -m ruff format --check $(QUALITY_PATHS)

quality-typecheck:
	python3 -m mypy apps/api/app/core apps/api/app/security apps/api/app/repositories/scoped.py apps/api/app/db/unit_of_work.py

quality-security:
	python3 -m bandit -q -r apps/api/app/core apps/api/app/security apps/api/app/repositories/scoped.py apps/api/app/db/unit_of_work.py

quality: quality-test quality-lint quality-format quality-typecheck quality-security

quality-audit-full:
	-python3 -m ruff check apps/api/app tests
	-python3 -m ruff format --check apps/api/app tests
	-python3 -m bandit -q -r apps/api/app

portal-build:
	cd apps/admin-portal && npm install && npm run build

smoke: wait-api
	$(MAKE) health
	$(MAKE) smoke-runtime
	$(MAKE) smoke-sprint-12
	$(MAKE) smoke-sprint-13
	$(MAKE) smoke-sprint-18-1
	$(MAKE) smoke-sprint-18-2
	$(MAKE) smoke-sprint-18-3
	$(MAKE) portal-build

db-upgrade:
	cd apps/api && alembic upgrade head

db-downgrade:
	cd apps/api && alembic downgrade -1

db-current:
	cd apps/api && alembic current
