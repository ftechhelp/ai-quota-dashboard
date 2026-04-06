# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A Python dashboard for monitoring quotas across different AI/service subscriptions.

## Python Tooling

The `.gitignore` includes entries for `uv`, `ruff`, `marimo`, `poetry`, `pdm`, and `pixi`. Prefer `uv` for dependency management and `ruff` for linting/formatting unless the project establishes otherwise.

Common commands (adapt once tooling is confirmed):

```bash
uv run python <file>        # Run a script
uv run pytest               # Run tests
uv run pytest tests/test_foo.py::test_bar  # Run a single test
uv run ruff check .         # Lint
uv run ruff format .        # Format
```
