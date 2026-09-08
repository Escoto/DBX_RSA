.PHONY: help deploy release seed reseed recreate-ddl start stop

# Colors
CYAN := \033[0;36m
GREEN := \033[0;32m
RESET := \033[0m

# The app's service principal is created with the app and changes whenever the
# app is recreated, so it is resolved from the deployed app at seed time rather
# than written here. Override with APP_SP_CLIENT_ID=<id> if needed.
APP_SP_CLIENT_ID ?=
PROFILE          := movies
INSTANCE         := movies-app-dev
APP              := movies-app-dev
# 80 polls x 15s = 20 minutes. A cold Lakebase start is usually 10-15.
START_MAX_POLLS  := 80
# WSL has no bare `python` — only python3 / python3.11 — and 3.11 is the
# one carrying psycopg + databricks-sdk, matching the Apps runtime.
PYTHON           := python3.11

# $(call SEED,<extra args>): resolve the app SP, refuse to run without it, seed.
define SEED
	@sp="$(APP_SP_CLIENT_ID)"; \
	test -n "$$sp" || sp=$$(databricks apps get $(APP) -p $(PROFILE) -o json | $(PYTHON) -c "import json,sys; print(json.load(sys.stdin).get('service_principal_client_id',''))"); \
	test -n "$$sp" || { echo "Could not resolve the service principal of app $(APP). Is it deployed?"; exit 1; }; \
	echo "Granting to app service principal $$sp"; \
	DATABRICKS_CONFIG_PROFILE=$(PROFILE) $(PYTHON) src/seed/seed_lakebase.py --app-sp-client-id $$sp $(1)
endef

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "$(GREEN)%-12s$(RESET) %s\n", $$1, $$2}'

deploy: ## Validate and deploy bundle resources.
	@echo "$(CYAN)Deploying to Databricks...$(RESET)"
	@databricks bundle validate
	@databricks bundle deploy
	@echo "$(GREEN)Done.$(RESET)"

release: ## Deploy bundle resources and start a new app deployment.
	@echo "$(CYAN)Deploying Bundle...$(RESET)"
	@databricks bundle validate
	@databricks bundle deploy
	@echo "$(CYAN)Deploying App...$(RESET)"
	@databricks bundle run movies_app
	@echo "$(GREEN)Done.$(RESET)"

start: ## Start the database, wait for it, then start the app.
	@echo "$(CYAN)Starting Database...$(RESET)"
	@databricks database update-database-instance $(INSTANCE) stopped --json '{"name":"$(INSTANCE)","stopped":false}' -p $(PROFILE) > /dev/null
	@printf "Waiting for $(INSTANCE) to become AVAILABLE"
	@n=0; until databricks database get-database-instance $(INSTANCE) -p $(PROFILE) -o json | grep -q '"state": "AVAILABLE"'; do n=$$((n+1)); if [ $$n -ge $(START_MAX_POLLS) ]; then echo ""; echo "Gave up waiting. Last reported state:"; databricks database get-database-instance $(INSTANCE) -p $(PROFILE) -o json | grep '"state"'; exit 1; fi; printf "."; sleep 15; done; echo " AVAILABLE"
	@echo "$(CYAN)Starting App...$(RESET)"
	@databricks apps start $(APP) -p $(PROFILE)
	@echo "$(GREEN)Done. Deploy with 'make release' now, not before.$(RESET)"

stop: ## Stop the app, then the database. Order matters.
	@echo "$(CYAN)Stopping App...$(RESET)"
	@databricks apps stop $(APP) -p $(PROFILE) > /dev/null
	@echo "$(CYAN)Stopping Database...$(RESET)"
	@databricks database update-database-instance $(INSTANCE) stopped --json '{"name":"$(INSTANCE)","stopped":true}' -p $(PROFILE) > /dev/null
	@echo "$(GREEN)Done.$(RESET)"

seed: ## Apply ddl.sql and load/update seed data; no data is destroyed.
	@echo "$(CYAN)Seeding Lakebase...$(RESET)"
	$(call SEED,)
	@echo "$(GREEN)Done.$(RESET)"

reseed: ## Truncate all tables and reload fresh seed data.
	@echo "$(CYAN)Re-seeding Lakebase (truncate + reload)...$(RESET)"
	$(call SEED,--reset)
	@echo "$(GREEN)Done.$(RESET)"

recreate-ddl: ## Drop and rebuild the schema, then reload seed data.
	@echo "$(CYAN)Recreating schema from ddl.sql...$(RESET)"
	$(call SEED,--recreate)
	@echo "$(GREEN)Done.$(RESET)"
