.PHONY: help deploy release seed reseed recreate-ddl

# Colors
CYAN := \033[0;36m
GREEN := \033[0;32m
RESET := \033[0m

APP_SP_CLIENT_ID := 010ae2f6-6206-498c-a005-17daf4850a48

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

seed: ## Apply ddl.sql and load/update seed data; no data is destroyed.
	@echo "$(CYAN)Seeding Lakebase...$(RESET)"
	@python src/seed/seed_lakebase.py --app-sp-client-id $(APP_SP_CLIENT_ID)
	@echo "$(GREEN)Done.$(RESET)"

reseed: ## Truncate all tables and reload fresh seed data.
	@echo "$(CYAN)Re-seeding Lakebase (truncate + reload)...$(RESET)"
	@python src/seed/seed_lakebase.py --app-sp-client-id $(APP_SP_CLIENT_ID) --reset
	@echo "$(GREEN)Done.$(RESET)"

recreate-ddl: ## Drop and rebuild the schema, then reload seed data.
	@echo "$(CYAN)Recreating schema from ddl.sql...$(RESET)"
	@python src/seed/seed_lakebase.py --app-sp-client-id $(APP_SP_CLIENT_ID) --recreate
	@echo "$(GREEN)Done.$(RESET)"
