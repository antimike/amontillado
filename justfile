# amontillado task runner. `just --list` shows the recipes.

# List recipes.
default:
    @just --list

# Run the test suite.
test *args:
    uv run pytest {{args}}

# Run only the nvim integration tests (nvim on PATH; plugins from AMO_TEST_NVIM_PLUGINS,
# default lazy.nvim's directory).
test-nvim *args:
    uv run pytest -m nvim {{args}}

# Lint and check formatting (what CI runs).
lint:
    uv run ruff check .
    uv run ruff format --check .

# Check the Lua examples' formatting (stylua on PATH; docs/examples/nvim/stylua.toml).
lint-lua:
    stylua --check docs/examples/nvim

# Regenerate the shipped config template from the key table (amontillado.config_keys).
config-template:
    uv run python -c "from amontillado.config_keys import template; print(template(), end='')" > src/amontillado/config.template.yaml

# Format and apply safe lint fixes.
fmt:
    uv run ruff format .
    uv run ruff check --fix .

# Sample Wallhaven and report metric distributions (tools/calibrate.py; needs the network).
calibrate *args:
    uv run tools/calibrate.py {{args}}

# Open GTK4 apps on the libadwaita template, rendered from this checkout (`--help` for usage).
libadwaita-live-test *args:
    tools/libadwaita-live-test.sh {{args}}

# Move the template registry's pins to each repository's head (tools/registry.py; needs the network).
registry *args:
    uv run tools/registry.py {{args}}

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
