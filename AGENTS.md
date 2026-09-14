# AGENTS.md

## Project overview

This repository is a small Python CLI app for tracking personal-finance records in a local SQLite database. The package is named `bankhuman`, and the console entry point is `bankhuman`.

Key docs:
- [README.md](README.md)

## Repository layout

- `bankhuman/cli.py`: interactive terminal interface and command-line entry point.
- `bankhuman/database.py`: SQLite schema, inserts, and queries.
- `bankhuman/models.py`: domain dataclasses (`Product`, `Registry`, `ProductType`).
- `tests/test_database.py`: project tests; uses the standard-library `unittest` runner.
- `data/`: default location for the SQLite database when running the app locally.

## Coding conventions

- Keep the domain model in `bankhuman/models.py` and persistence in `bankhuman/database.py`.
- Prefer `Decimal` over floating-point types for money values and keep currency handling explicit.
- Treat SQLite as the source of truth for persisted records; keep UI code in `cli.py` and business/domain logic in models and database helpers.
- Preserve the existing CLI behavior: interactive menu, data/bankhuman.db default path, and local-first storage.
- When changing database structure, keep migrations in mind for the local SQLite file; this project does not appear to use Alembic or a separate migration framework.

## Validation

Run the test suite with:

```powershell
python -m unittest discover -s tests -v
```

For a local install/editable package workflow:

```powershell
python -m pip install -e .
```

## Practical guidance for agents

- If a task changes the data schema, update the corresponding model and database code together.
- If a task changes the CLI, keep it user-friendly and minimal; the project favors a simple terminal menu over elaborate frameworks.
- Prefer small, focused edits; this repo is intentionally compact and easy to reason about.
- Use existing tests as the first validation target before adding new behavior or broad refactors.
