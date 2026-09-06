.PHONY: help deploy

# Colors
CYAN := \033[0;36m
GREEN := \033[0;32m
RESET := \033[0m

help: ## Show commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "$(GREEN)%-12s$(RESET) %s\n", $$1, $$2}'

deploy:
	@echo "$(CYAN)Deploying to Databricks...$(RESET)"
	@databricks bundle validate
	@databricks bundle deploy
	@echo "$(GREEN)Done.$(RESET)"

release:
	@echo "$(CYAN)Deploying Bundle...$(RESET)"
	@databricks bundle validate
	@databricks bundle deploy
	@echo "$(CYAN)Deploying App...$(RESET)"
	@databricks bundle run movies_app
	@echo "$(GREEN)Done.$(RESET)"
