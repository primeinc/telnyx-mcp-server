# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

The Telnyx MCP Server is an official integration that enables AI assistants to interact with Telnyx's telephony, messaging, and AI assistant APIs through the Model Context Protocol (MCP). It supports both local mode (stdio transport) and remote mode (HTTP/SSE with OAuth).

## Essential Commands

### Development Setup
```bash
# Install dependencies (creates .venv automatically)
uv sync --all-extras

# Run local MCP server (for Claude Desktop)
uv run telnyx-mcp-server

# Run remote server for development
uv run uvicorn telnyx_mcp_server.remote.server:app --reload

# Run production-like remote server
uv run gunicorn -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --timeout 600 telnyx_mcp_server.remote.server:app
```

### Testing
```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/test_config.py

# Run with coverage
uv run pytest --cov=telnyx_mcp_server

# Run tests matching pattern
uv run pytest -k "test_message"
```

### Code Quality
```bash
# Format code
uv run ruff format .

# Lint code
uv run ruff check .

# Fix auto-fixable issues
uv run ruff check --fix .
```

### Package Management
```bash
# Add dependency
uv add package-name

# Add dev dependency
uv add --dev package-name

# Update dependencies
uv lock --upgrade

# Export requirements.txt (for Azure deployment)
uv export --format requirements-txt > requirements.txt
```

## Architecture & Key Components

### Core Architecture
- **MCP Server Core** (`src/telnyx_mcp_server/mcp.py`): Singleton MCP server instance shared across all modules
- **Local Server** (`server.py`): Entry point for stdio transport (Claude Desktop)
- **Remote Server** (`remote/server.py`): FastAPI-based HTTP/SSE server with OAuth for cloud deployment
- **Tool Registration**: Tools are auto-discovered and registered via decorators (@mcp.tool())

### Authentication Flow (Remote Mode)

#### Built-in Auth with Federated Identity Credentials (FIC)
When deployed to Azure App Service, the server uses Built-in Authentication (Easy Auth) with Federated Identity Credentials for secretless authentication:
1. App Service has a system-assigned managed identity
2. OAuth app registration trusts the managed identity via FIC
3. No client secrets or certificates needed in the App Service
4. Authentication flows:
   - **Browser-based**: Use `/.auth/login/aad` endpoint
   - **Programmatic (MSAL)**: Send tokens in Authorization header
5. Server validates auth via `X-MS-CLIENT-PRINCIPAL` header (Built-in Auth) or JWT tokens (MSAL)

#### OAuth Flow Details
1. OAuth via Azure AD for user authentication
2. JWT tokens for API authentication
3. Redis-backed auth store for production (in-memory for development)
4. PII redaction in logs via structured logging

### Tool Organization
Tools are grouped by functionality in `src/telnyx_mcp_server/tools/`:
- `assistants.py`: AI assistant management
- `call_control.py`: Voice call operations
- `messaging.py`: SMS/MMS functionality
- `phone_numbers.py`: Number management
- `connections.py`: Voice connections
- `cloud_storage.py`: S3-compatible storage
- `embeddings.py`: Website/file embeddings
- `secrets.py`: Secrets management

### Webhook Support
- Built-in ngrok integration for local webhook testing
- Webhook receiver runs on separate thread
- Parent process monitoring for automatic cleanup
- Event history tracking accessible via tools

## Important Implementation Details

### Error Handling
- All tools use consistent error handling via `handle_api_error` decorator
- Structured error responses with proper MCP error codes
- Automatic retry logic for transient failures

### Configuration
- Environment-based config via Pydantic Settings
- Tool filtering support (enable/disable specific tools)
- Multi-environment support (dev/staging/production)
- CORS configuration for remote deployments

### Logging & Monitoring
- Structured logging with structlog
- Automatic PII redaction in logs
- Trace ID propagation for request tracking
- Azure Application Insights integration

### Testing Strategy
- Mock-based unit tests for API interactions
- Integration tests for OAuth flows
- End-to-end tests for remote server
- Smoke tests for basic functionality

## Azure Deployment

The project includes automated deployment to Azure App Service:
- GitHub Actions workflow (`.github/workflows/azure-deploy.yml`)
- Dynamic environment configuration
- Automatic requirements.txt generation
- Health check endpoints
- Multi-worker Gunicorn configuration

### Infrastructure Components
- **App Service**: Linux-based with system-assigned managed identity
- **Key Vault**: Stores secrets accessed via managed identity
- **App Registration with FIC**: OAuth app that trusts the App Service's managed identity
- **Built-in Auth**: Configured via `authsettingsV2` with `OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID`
- **No certificates or client secrets** required in production

## Key Files to Understand

1. **`src/telnyx_mcp_server/mcp.py`**: Core MCP server setup and configuration
2. **`src/telnyx_mcp_server/remote/server.py`**: FastAPI app for remote deployment
3. **`src/telnyx_mcp_server/remote/auth.py`**: OAuth and JWT authentication
4. **`src/telnyx_mcp_server/utils/logging_config.py`**: Structured logging setup
5. **`src/telnyx_mcp_server/config.py`**: Configuration management
6. **`src/telnyx_mcp_server/tools/__init__.py`**: Tool auto-discovery

## Development Tips

- Use `uv run` for all commands - no need to activate virtual environment
- Tools are automatically discovered when imported in `tools/__init__.py`
- All API interactions should use the centralized Telnyx client in `telnyx/client.py`
- Follow existing patterns for error handling and response formatting
- Ensure PII is not logged (automatic redaction handles most cases)
- Run code quality checks before committing
