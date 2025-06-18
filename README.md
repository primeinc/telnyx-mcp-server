# Telnyx Model Context Protocol (MCP) Server

Official Telnyx Model Context Protocol (MCP) Server that enables interaction with powerful telephony, messaging, and AI assistant APIs. This server allows MCP clients like Claude Desktop, Claude.ai, Cursor, Windsurf, OpenAI Agents and others to manage phone numbers, send messages, make calls, and create AI assistants.

## Deployment Options

This server supports two deployment modes:

1. **Local Mode** - Run locally via stdio transport for Claude Desktop and other local MCP clients
2. **Remote Mode** - Deploy as a cloud service with OAuth authentication for Claude.ai custom integrations

For remote deployment instructions, see [REMOTE_DEPLOYMENT.md](REMOTE_DEPLOYMENT.md).

## Quickstart with Claude Desktop

1. Get your API key from the [Telnyx Portal](https://portal.telnyx.com/#/api-key).
2. Install `uvx` (Python package manager), install with `curl -LsSf https://astral.sh/uv/install.sh | sh` , `brew install uv` or see the `uv` repo for additional install methods.
3. Go to Claude > Settings > Developer > Edit Config > claude_desktop_config.json to include the following:

```json
{
  "mcpServers": {
    "Telnyx": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/team-telnyx/telnyx-mcp-server.git", "telnyx-mcp-server"],
      "env": {
        "TELNYX_API_KEY": "<insert-your-api-key-here>"
      }
    }
  }
}
```

If you're using Windows, you will have to enable "Developer Mode" in Claude Desktop to use the MCP server. Click "Help" in the hamburger menu at the top left and select "Enable Developer Mode".

## Running After Download

1. Get your API key from the [Telnyx Portal](https://portal.telnyx.com/#/api-key).

2. Install `uvx` (Python package manager), install with `curl -LsSf https://astral.sh/uv/install.sh | sh` , `brew install uv` or see the `uv` repo for additional install methods.

3. **Clone the Git Repository**
   Use Git to download the Telnyx MCP Server locally:
   ```bash
   git clone https://github.com/team-telnyx/telnyx-mcp-server.git
   cd telnyx-mcp-server
   ```

4. **Configure and Run with uvx**
   In your Claude config, you can reference the local folder by using the `--from` argument. For example:
   ```json
   {
     "mcpServers": {
       "Telnyx": {
         "command": "uvx",
         "args": ["--from", "/path/to/telnyx-mcp-server", "telnyx-mcp-server"],
         "env": {
           "TELNYX_API_KEY": "<insert-your-api-key-here>"
         }
       }
     }
   }
   ```

5. This instructs Claude to run the server from the folder you cloned.
Replace “/path/to/telnyx-mcp-server” with the actual location of the repository.

## Available Tools

### Assistant Tools
- Create AI assistants with custom instructions and configurations
- List existing assistants
- Get assistant details
- Update assistant properties
- Delete assistants
- Get assistant TEXML configurations

### Call Control Tools
- Make outbound phone calls
- Hang up active calls
- Transfer calls to new destinations
- Play audio files during calls
- Stop audio playback
- Send DTMF tones
- Speak text using text-to-speech

### Messaging Tools
- Send SMS and MMS messages
- Get message details
- Access and view ongoing SMS conversations (`resource://sms/conversations`)

### Phone Number Tools
- List your phone numbers
- Buy new phone numbers
- Update phone number configurations
- List available phone numbers

### Connection Tools
- List voice connections
- Get connection details
- Update connection configurations

### Cloud Storage Tools
- Create buckets compatible with Telnyx Cloud Storage
- List buckets across all regions
- Upload files
- Download files
- List objects in a bucket
- Delete objects
- Get bucket location information

### Embeddings Tools
- List existing embedded buckets
- Scrape and embed a website URL
- Create embeddings for your own files

### Secrets Manager Tools
- List integration secrets
- Create new bearer or basic secrets
- Delete integration secrets

## Tool Filtering

You can selectively enable or disable specific tools when running the MCP server. This is useful when you only need a subset of the available functionality.

### Listing Available Tools

To see all available tools:

```bash
uvx --from /path/to/telnyx-mcp-server telnyx-mcp-server --list-tools
```

### Enabling Specific Tools

You can enable only specific tools using either:

1. **Command-line argument**:
   ```bash
   uvx --from /path/to/telnyx-mcp-server telnyx-mcp-server --tools "send_message,get_message,list_phone_numbers"
   ```

2. **Environment variable**:
   ```json
   {
     "mcpServers": {
       "Telnyx": {
         "command": "uvx",
         "args": ["--from", "/path/to/telnyx-mcp-server", "telnyx-mcp-server"],
         "env": {
           "TELNYX_API_KEY": "<insert-your-api-key-here>",
           "TELNYX_MCP_TOOLS": "send_message,get_message,list_phone_numbers"
         }
       }
     }
   }
   ```

### Excluding Specific Tools

You can exclude specific tools while enabling all others:

1. **Command-line argument**:
   ```bash
   uvx --from /path/to/telnyx-mcp-server telnyx-mcp-server --exclude-tools "make_call,send_dtmf"
   ```

2. **Environment variable**:
   ```json
   {
     "mcpServers": {
       "Telnyx": {
         "command": "uvx",
         "args": ["--from", "/path/to/telnyx-mcp-server", "telnyx-mcp-server"],
         "env": {
           "TELNYX_API_KEY": "<insert-your-api-key-here>",
           "TELNYX_MCP_EXCLUDE_TOOLS": "make_call,send_dtmf"
         }
       }
     }
   }
   ```

## Example Usage

Try asking Claude:

* "Create an AI agent that can handle customer service for an e-commerce business"
* "Send a text message to +5555551234 saying 'Your appointment is confirmed for tomorrow at 3pm'"
* "Make a call to my customer at +5555551234 and transfer them to my support team"
* "Find me a phone number in Chicago with area code 312"
* "Create an auto-attendant system using Telnyx AI assistants and voice features"

## Webhook Receiver

The MCP server includes a webhook receiver that can handle Telnyx webhooks directly through ngrok. This is useful for receiving call events and other notifications from Telnyx.

### Enabling Webhooks

To enable the webhook receiver, you can either use the `--webhook-enabled` command-line flag or set the `WEBHOOK_ENABLED=true` environment variable. If an `NGROK_AUTHTOKEN` is also provided (see 'Ngrok Integration' below), the ngrok tunnel will be automatically attempted when the server starts. The command-line flag takes precedence if both are set.

**Using Command-Line Flag:**

```bash
telnyx-mcp-server --webhook-enabled --ngrok-enabled
```

**Using Environment Variable:**

Alternatively, set the `WEBHOOK_ENABLED=true` environment variable. This is often convenient when configuring via MCP client settings (see 'Webhook Configuration in Claude Desktop' below) or in `.env` files.

```bash
# Example for your shell
export WEBHOOK_ENABLED=true
export NGROK_AUTHTOKEN=your_ngrok_token # Also needed for ngrok
telnyx-mcp-server
```

### Ngrok Integration

To enable ngrok tunneling:

1. Get an ngrok authentication token from [ngrok.com](https://ngrok.com/)
2. Set the `NGROK_AUTHTOKEN` environment variable or use the `--ngrok-authtoken` flag:

```bash
# Using NGROK_AUTHTOKEN environment variable (recommended)
export NGROK_AUTHTOKEN=your_ngrok_token
telnyx-mcp-server --webhook-enabled # Or use WEBHOOK_ENABLED=true env var

# Or using --ngrok-authtoken command line flag
telnyx-mcp-server --webhook-enabled --ngrok-authtoken your_ngrok_token
```
If `NGROK_AUTHTOKEN` is set, the `--ngrok-enabled` flag is generally not required when webhooks are active.

When ngrok is enabled, the server will print the public URL that can be used to configure webhooks in the Telnyx Portal.

**Important:** If ngrok fails to initialize (e.g., due to an invalid authtoken, network issues, or conflicts with another ngrok process), the MCP server will exit on startup. Check the server logs for details (see Troubleshooting section).

### Parent Process Monitoring

The MCP server monitors the parent process (Claude Desktop) and automatically exits when the parent process is gone. This ensures proper cleanup of resources even if Claude Desktop closes unexpectedly.


### Webhook Monitoring and Runtime Control

- You can inspect the current webhook and ngrok status by querying the `resource://webhook/info` resource.
- To retrieve a history of received webhook events, use the `get_webhook_events` tool.

### Webhook Configuration in Claude Desktop

To enable webhooks in Claude Desktop, update your configuration:

```json
{
  "mcpServers": {
    "Telnyx": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/team-telnyx/telnyx-mcp-server.git", "telnyx-mcp-server"],
      "env": {
        "TELNYX_API_KEY": "<insert-your-api-key-here>",
        "NGROK_AUTHTOKEN": "<insert-your-ngrok-token-here>",
        "WEBHOOK_ENABLED": "true", // Enables webhooks via environment variable
        // Alternatively, you can use command-line flags in "args" instead of WEBHOOK_ENABLED in env:
        // e.g., "args": ["--from", "git+https://github.com/team-telnyx/telnyx-mcp-server.git", "telnyx-mcp-server", "--webhook-enabled"],
      }
    }
  }
}
```

### Webhook Example

﻿﻿﻿﻿<img width="704" alt="Screenshot Webhook" src="https://github.com/user-attachments/assets/2e1f4a47-df24-4e35-acdf-765ef4a71578" />

## Remote MCP Now Available

Telnyx now offers a remote MCP implementation based on the latest MCP specification. This allows you to access Telnyx's powerful communications APIs through a remotely hosted MCP server. No need to run the server locally. Learn more in the [official documentation](https://developers.telnyx.com/docs/mcp/remote-mcp).

## Running the Remote Server

The remote server provides an HTTP/SSE interface for the Telnyx MCP server, suitable for cloud deployment:

```bash
# Run locally with gunicorn (same as Azure production)
# Set LOG_LEVEL environment variable (DEBUG, INFO, WARNING, ERROR, CRITICAL)
export LOG_LEVEL=DEBUG  # or INFO for production
uv run gunicorn -w 1 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --timeout 600 --chdir src --access-logfile - --error-logfile - --log-level $LOG_LEVEL telnyx_mcp_server.remote.server:app

# Or run with uvicorn for development
uv run uvicorn src.telnyx_mcp_server.remote.server:app --host 0.0.0.0 --port 8000 --reload --log-level debug
```

The server provides:
- OAuth 2.0 authentication with Azure AD
- JWT-based API authentication
- MCP protocol over HTTP/SSE
- Health check endpoint at `/health`

## CI/CD with GitHub Actions

This project includes GitHub Actions workflow for automated deployment to Azure App Service. To set it up:

1. **Create GitHub Secrets**:
   - `AZURE_CLIENT_ID`: Your Azure app registration client ID
   - `AZURE_TENANT_ID`: Your Azure tenant ID
   - `AZURE_SUBSCRIPTION_ID`: Your Azure subscription ID
   - `TELNYX_API_KEY`: Your Telnyx API key
   - `JWT_SECRET_KEY`: A secure secret for JWT signing (generate with: `python -c 'import secrets; print(secrets.token_urlsafe(32))'`)
   - `AZURE_CLIENT_SECRET`: Your Azure app registration client secret

2. **Set up Azure OpenID Connect** (recommended):
   Follow the [Azure documentation](https://docs.microsoft.com/azure/app-service/deploy-github-actions) to create federated credentials for your GitHub repository.

3. **Deploy**:
   Push to `main` or `feature/remote-mcp-server` branch to trigger automatic deployment.

## Development

This project uses [uv](https://docs.astral.sh/uv/) for dependency management and development workflow.

### Prerequisites

1. Install uv:
```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# or
wget -qO- https://astral.sh/uv/install.sh | sh

# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

2. Clone the repository:
```bash
git clone https://github.com/team-telnyx/telnyx-mcp-server.git
cd telnyx-mcp-server
```

### Setup Development Environment

```bash
# Install all dependencies (including dev dependencies)
uv sync --all-extras

# The virtual environment is created automatically at .venv/
# No need to activate it - uv handles this for you!
```

### Running the Server Locally

```bash
# Run the MCP server (local mode)
uv run telnyx-mcp-server

# Run the remote server for development
uv run uvicorn src.telnyx_mcp_server.remote.server:app --reload

# Run any Python script
uv run python scripts/test_remote_server.py
```

### Running Tests

```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/test_config.py

# Run with coverage
uv run pytest --cov=telnyx_mcp_server
```

### Code Quality

```bash
# Format code
uv run ruff format .

# Lint code
uv run ruff check .

# Type checking (if mypy is added)
uv run mypy src/
```

### Managing Dependencies

```bash
# Add a new dependency
uv add requests

# Add a development dependency
uv add --dev pytest-mock

# Update dependencies
uv sync

# Update specific package
uv add 'fastapi>=0.115.0'

# Remove a dependency
uv remove package-name
```

### Working with uv

Key benefits of uv:
- **No virtual environment activation needed** - `uv run` automatically uses the project environment
- **Fast** - 10-100x faster than traditional package managers
- **Reproducible** - `uv.lock` ensures everyone gets the same versions
- **Simple** - One tool for all Python package management

Common commands:
```bash
# Show project dependencies tree
uv tree

# Export requirements (if needed for compatibility)
uv export --format requirements-txt > requirements.txt
```

For more details, see the [uv documentation](https://docs.astral.sh/uv/).

3. Create a `.env` file and add your Telnyx API key:
```bash
echo "TELNYX_API_KEY=YOUR_API_KEY" > .env
```

4. Run the tests to make sure everything is working:
```bash
pytest
```

5. Install the server in Claude Desktop: `mcp install src/telnyx_mcp_server/server.py`
6. Debug and test locally with MCP Inspector: `mcp dev src/telnyx_mcp_server/server.py`

## Contributing

See [DEVELOPMENT.md](DEVELOPMENT.md) for detailed development instructions including code quality tools.

## License

This project is licensed under the Apache License 2.0. See [LICENSE](LICENSE) for details.

## Troubleshooting

Logs when running with Claude Desktop can be found at:

* **Windows**: `%APPDATA%\Claude\logs\mcp-server-telnyx.log`
* **macOS**: `~/Library/Logs/Claude/mcp-server-telnyx.log`

### MCP Telnyx: spawn uvx ENOENT

If you encounter the error "MCP Telnyx: spawn uvx ENOENT", confirm its absolute path by running this command in your terminal:

```bash
which uvx
```

Once you obtain the absolute path (e.g., `/usr/local/bin/uvx`), update your configuration to use that path (e.g., `"command": "/usr/local/bin/uvx"`). This ensures that the correct executable is referenced.


### Server Fails to Start (Especially with Webhooks/Ngrok)

If the MCP server fails to start, particularly if you have webhooks enabled, it might be due to an issue with ngrok initialization.
One common cause is an existing ngrok process running in the background, potentially from a previous server instance that didn't shut down cleanly.

*   **Check for running processes:** Use commands like `ps aux | grep telnyx-mcp-server` (Linux/macOS) or check Task Manager (Windows) for any lingering `telnyx-mcp-server` processes. Since ngrok is managed internally by the server, you typically won't see a separate 'ngrok' process.
*   **Kill old processes:** If found, terminate these old processes.
*   **Check logs:** Review the server logs (locations mentioned above) for specific error messages related to ngrok or server startup.
