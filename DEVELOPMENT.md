# Development Guide

This guide covers the development workflow for the Telnyx MCP Server using [uv](https://docs.astral.sh/uv/).

## Table of Contents

- [Prerequisites](#prerequisites)
- [Getting Started](#getting-started)
- [Project Structure](#project-structure)
- [Development Workflow](#development-workflow)
- [Testing](#testing)
- [Code Quality](#code-quality)
- [Dependency Management](#dependency-management)
- [Common Tasks](#common-tasks)
- [Troubleshooting](#troubleshooting)

## Prerequisites

### Install uv

uv is a fast Python package manager written in Rust. Install it using one of these methods:

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Homebrew (macOS)
brew install uv

# Or with pip (if you have Python already)
pip install uv
```

Verify installation:
```bash
uv --version
```

## Getting Started

1. **Clone the repository:**
   ```bash
   git clone https://github.com/team-telnyx/telnyx-mcp-server.git
   cd telnyx-mcp-server
   ```

2. **Set up the development environment:**
   ```bash
   # This creates a .venv and installs all dependencies including dev tools
   uv sync --all-extras
   ```

3. **Create environment configuration:**
   ```bash
   cp .env.example .env
   # Edit .env and add your TELNYX_API_KEY
   ```

## Project Structure

```
telnyx-mcp-server/
├── src/
│   └── telnyx_mcp_server/     # Main package
│       ├── mcp.py             # MCP server core
│       ├── server.py          # Local server entry point
│       ├── remote/            # Remote server implementation
│       ├── tools/             # MCP tool implementations
│       └── telnyx/            # Telnyx API client
├── tests/                     # Test suite
├── scripts/                   # Utility scripts
├── pyproject.toml            # Project configuration
├── uv.lock                   # Locked dependencies
└── .venv/                    # Virtual environment (auto-created)
```

## Development Workflow

### Running the Server

```bash
# Run MCP server (local mode - for Claude Desktop)
uv run telnyx-mcp-server

# Run with specific tools enabled
uv run telnyx-mcp-server --tools "send_message,list_phone_numbers"

# Run remote server (HTTP/SSE mode - for Claude.ai)
uv run uvicorn src.telnyx_mcp_server.remote.server:app --reload

# Run with custom host/port
uv run uvicorn src.telnyx_mcp_server.remote.server:app --host 0.0.0.0 --port 8000 --reload
```

### Making Changes

1. **Create a feature branch:**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes and test locally:**
   ```bash
   # Run the server to test changes
   uv run telnyx-mcp-server

   # Run specific tests
   uv run pytest tests/test_your_feature.py -v
   ```

3. **Ensure code quality:**
   ```bash
   # Format code
   uv run ruff format .

   # Check linting
   uv run ruff check .

   # Run all tests
   uv run pytest
   ```

## Testing

### Running Tests

```bash
# Run all tests
uv run pytest

# Run with verbose output
uv run pytest -v

# Run specific test file
uv run pytest tests/test_config.py

# Run specific test function
uv run pytest tests/test_config.py::test_get_api_base_url

# Run with coverage
uv run pytest --cov=telnyx_mcp_server --cov-report=html

# Run tests matching a pattern
uv run pytest -k "test_message"

# Run tests in parallel (if pytest-xdist is installed)
uv run pytest -n auto
```

### Writing Tests

Tests are located in the `tests/` directory. Follow the existing patterns:

```python
# tests/test_your_feature.py
import pytest
from telnyx_mcp_server.your_module import your_function

def test_your_function():
    """Test description."""
    result = your_function()
    assert result == expected_value

@pytest.mark.asyncio
async def test_async_function():
    """Test async function."""
    result = await async_function()
    assert result == expected_value
```

## Code Quality

### Linting and Formatting

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting:

```bash
# Format code (modifies files)
uv run ruff format .

# Check linting issues
uv run ruff check .

# Fix auto-fixable linting issues
uv run ruff check --fix .

# Check specific file
uv run ruff check src/telnyx_mcp_server/server.py
```

### Pre-commit Checks

Before committing, run:

```bash
# Format, lint, and test
uv run ruff format . && uv run ruff check . && uv run pytest
```

## Dependency Management

### Adding Dependencies

```bash
# Add a runtime dependency
uv add requests

# Add a specific version
uv add 'fastapi>=0.110.0'

# Add from git
uv add git+https://github.com/encode/httpx

# Add a development dependency
uv add --dev pytest-mock

# Add optional dependencies (extras)
uv add --optional webhook ngrok
```

### Updating Dependencies

```bash
# Update all dependencies to latest compatible versions
uv lock --upgrade

# Update specific package
uv lock --upgrade-package fastapi

# Sync environment after manual pyproject.toml changes
uv sync
```

### Removing Dependencies

```bash
# Remove a dependency
uv remove requests

# Remove a dev dependency
uv remove --dev pytest-mock
```

### Viewing Dependencies

```bash
# Show dependency tree
uv tree

# Show package details
uv tree --package package-name
```

## Common Tasks

### Adding a New MCP Tool

1. Create a new file in `src/telnyx_mcp_server/tools/`:
   ```python
   # src/telnyx_mcp_server/tools/your_tool.py
   from ..mcp import mcp

   @mcp.tool()
   async def your_tool_name(param1: str, param2: int) -> dict:
       """Tool description.

       Args:
           param1: Description of param1
           param2: Description of param2

       Returns:
           dict: Tool response
       """
       # Implementation
       return {"result": "success"}
   ```

2. Import in `src/telnyx_mcp_server/tools/__init__.py`

3. Test your tool:
   ```bash
   uv run telnyx-mcp-server --tools "your_tool_name"
   ```

### Working with the Remote Server

```bash
# Start the remote server
uv run uvicorn src.telnyx_mcp_server.remote.server:app --reload

# Test endpoints
curl http://localhost:8000/health
curl http://localhost:8000/.well-known/mcp-openapi.json
```

### Debugging

```bash
# Run with debug logging
LOG_LEVEL=DEBUG uv run telnyx-mcp-server

# Run specific script with debugger
uv run python -m pdb scripts/test_remote_server.py

# Use ipython for interactive testing
uv add --dev ipython
uv run ipython
```

## Troubleshooting

### Common Issues

**Issue: Command not found: uv**
- Solution: Ensure uv is installed and in your PATH. Run the installation command again.

**Issue: No module named 'telnyx_mcp_server'**
- Solution: Run `uv sync` to ensure the project is installed in editable mode.

**Issue: Dependencies out of sync**
- Solution: Run `uv sync --all-extras` to update your environment.

**Issue: Tests failing due to missing dependencies**
- Solution: Make sure you've installed dev dependencies with `uv sync --all-extras`.

### Resetting Environment

If you encounter issues, you can reset your environment:

```bash
# Remove virtual environment
rm -rf .venv

# Remove lock file (if you want to re-resolve dependencies)
rm uv.lock

# Recreate everything
uv sync --all-extras
```

## CI/CD

The project uses GitHub Actions for CI/CD. Workflows are located in `.github/workflows/`:

- `remote-server-tests.yml`: Runs tests on PR changes
- `azure-deploy.yml`: Deploys to Azure on main branch pushes

All CI/CD workflows use uv for consistency with local development.

## Additional Resources

- [uv Documentation](https://docs.astral.sh/uv/)
- [MCP Protocol Specification](https://github.com/anthropics/mcp)
- [Telnyx API Documentation](https://developers.telnyx.com/)
- [Project README](README.md)
