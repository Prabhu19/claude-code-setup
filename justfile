#!/usr/bin/env just --justfile

set shell := ["zsh", "-cu"]

default:
  @just --list

# Setup
setup:
  uv venv
  uv pip install -e '.[dev]'

# Development
dev: setup
  @echo "Development environment ready"

# Testing
test:
  uv run pytest

# Code quality
lint:
  uv run ruff check .

format:
  uv run ruff format .
  uv run ruff check . --fix

typecheck:
  uv run mypy src

check: lint typecheck test
  @echo "✓ All checks passed"

# Building & Publishing
build:
  uv build

publish: check build
  uv publish

# Project commands
list-components:
  uv run claude-code-setup --list

install-all:
  uv run claude-code-setup

install component:
  uv run claude-code-setup {{ component }}

uninstall-all:
  uv run claude-code-setup --uninstall

# Utilities
clean:
  rm -rf dist/ build/ .eggs/ .ruff_cache/ .mypy_cache/ .pytest_cache/
  find . -type d -name "*.egg-info" -exec rm -rf {} +
  find . -type d -name __pycache__ -delete

help:
  @just --list
