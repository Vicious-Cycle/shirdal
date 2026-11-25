# Contributing to Shirdal

Contributions, bug reports, and pull requests are welcome.

## Local Setup

```bash
git clone https://github.com/Vicious-Cycle/shirdal.git
cd shirdal
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running Tests & Checks

Shirdal's test suite uses Python's standard `unittest` and runs offline via `MockAdapter` and mocked Bot API transport:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

If you have `ruff` and `mypy` installed:

```bash
ruff check src tests
mypy src
```

## Guidelines

- Keep `BotAPIAdapter` and core modules free of required third-party dependencies.
- Add unit tests under `tests/` for any new adapter method, filter, or context helper.
- Update the relevant page in `docs/` when changing public APIs.
