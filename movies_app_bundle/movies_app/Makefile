# Dev shortcuts, meant to be run from WSL in this directory (movies_app/).
# Node lives on the Windows side only, so the frontend targets drive Windows
# npm through WSL interop (cmd.exe); the current /mnt/c directory becomes its cwd.
# This file is dev tooling: nothing on the Databricks Apps runtime uses it.

.DEFAULT_GOAL := help
.PHONY: help setup run_back run_front build

VENV  := $(HOME)/.venvs/movies-app
PY    := $(VENV)/bin/python
PIP   := $(VENV)/bin/pip
STAMP := $(VENV)/.requirements-installed
NPM   := cmd.exe /c npm
PORT  ?= 8000

# A Makefile-level export reaches every recipe line. A bare `export` inside a
# recipe only lives for that one line, because each line runs in its own shell.
export DATABRICKS_CONFIG_PROFILE := movies
export DATABRICKS_APP_PORT := $(PORT)

CYAN  := \033[0;36m
GREEN := \033[0;32m
RESET := \033[0m

help: ## Show commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "$(GREEN)%-10s$(RESET) %s\n", $$1, $$2}'

# Real file target: the venv is created once, and requirements are reinstalled
# only when requirements.txt is newer than the stamp.
$(STAMP): requirements.txt
	@echo "$(CYAN)Installing backend requirements into $(VENV)...$(RESET)"
	@test -x $(PY) || python3.11 -m venv $(VENV)
	@$(PIP) install -q -r requirements.txt
	@touch $@

setup: $(STAMP) ## Create the Python 3.11 venv and install backend requirements

run_back: $(STAMP) ## Run the FastAPI backend on http://localhost:8000 (serves /api and frontend/dist)
	@echo "$(CYAN)Backend on http://localhost:$(PORT), profile $(DATABRICKS_CONFIG_PROFILE). Ctrl+C to stop.$(RESET)"
	@$(PY) -m backend.serve

run_front: ## Run the Vite dev server on http://localhost:5173 (Windows Node via interop; proxies /api to :8000)
	@echo "$(CYAN)Vite dev server on http://localhost:5173. Ctrl+C to stop.$(RESET)"
	@cd frontend && $(NPM) run dev

build: ## Build the SPA exactly as the Apps deployment does (npm ci, type-check, vite build)
	@$(NPM) run build
