# amontillado task runner. `just --list` shows the recipes.

# List recipes.
default:
    @just --list

# Run the test suite.
test *args:
    uv run pytest {{args}}

# Lint and check formatting (what CI runs).
lint:
    uv run ruff check .
    uv run ruff format --check .

# Format and apply safe lint fixes.
fmt:
    uv run ruff format .
    uv run ruff check --fix .

# Sample Wallhaven and report metric distributions (tools/calibrate.py; needs the network).
calibrate *args:
    uv run tools/calibrate.py {{args}}

# Install from this checkout into a pipx venv (a snapshot).
install:
    -pipx uninstall amontillado
    pipx install .

# Install editable: code changes in this checkout take effect immediately.
install-dev:
    -pipx uninstall amontillado
    pipx install --editable .

# Remove the pipx install.
uninstall:
    pipx uninstall amontillado
