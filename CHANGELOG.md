# Changelog

## [0.5.0] - Production Hardening Release

### Added
- **Redis-backed AsyncRedisAuthStore**: Replaced in-memory auth store with Redis-backed implementation
  - TTL support with automatic Redis expiration
  - Environment-configurable Redis URL via `REDIS_URL`
  - Fallback to in-memory store for development/test environments
  - Health check functionality for monitoring Redis connectivity
  - Comprehensive test coverage for both Redis and fallback modes

- **Enhanced Security and CORS**:
  - Restricted CORS policy to `MCP_ALLOWED_ORIGINS` environment variable
  - Added security headers: HSTS, Referrer-Policy, CSP, X-Content-Type-Options, X-Frame-Options
  - CORS violation logging at WARNING level with detailed request information
  - Trace ID tracking across all requests for better observability

- **Structured Logging with PII Redaction**:
  - Implemented structlog-based logging with JSON output for production
  - PIIRedactorProcessor to automatically redact sensitive data (tokens, passwords, emails, phone numbers, etc.)
  - Added timestamp, level, event, logger name, and trace_id to all log entries
  - Support for Azure Application Insights integration via `APPLICATION_INSIGHTS_KEY`
  - Configurable PII redaction via `ENABLE_PII_REDACTION` environment variable

- **Pydantic-based Schema Processing**:
  - Replaced docstring-based schema parsing with Pydantic models
  - Added schema models for common tools: MessageToolSchema, PhoneNumberListSchema, etc.
  - Argument validation using Pydantic with proper error handling
  - Support for registering custom tool schemas
  - Malformed schema handling and validation

- **Comprehensive Testing**:
  - End-to-end tests for OAuth login, code exchange, token resource fetch
  - SSE streaming tests with authentication failure/reconnection scenarios
  - JWT tampering, expiry, and scope validation tests
  - Redis auth store tests with fallback scenarios
  - PII redaction processor tests
  - Schema validation and tool argument testing

### Changed
- **Azure Deployment Configuration**:
  - Removed hardcoded Gunicorn worker count (`-w 1` removed)
  - Set `WEBSITE_RUN_FROM_PACKAGE=1` for improved startup performance
  - Enabled multiworker scaling by removing worker restrictions
  - Updated command line to use structured logging
  - Added readiness probe support via enhanced `/health` endpoint
  - Deployment logs now saved to `.github/actions/deploy-logs/` with retention

- **Health Check Enhancements**:
  - `/health` endpoint now includes auth store and MCP tools status
  - Returns HTTP 503 when components are unhealthy (proper readiness probe)
  - Added timestamp and component-specific health information
  - Includes Redis connectivity status when applicable

- **Environment Configuration**:
  - Updated `.env.example` with all new configuration options
  - Added Redis, CORS, and logging configuration variables
  - Production-ready default values for security headers

### Fixed
- Tool schema transformation now uses reliable Pydantic models instead of fragile docstring parsing
- Auth store now properly handles TTL and expiration in both Redis and fallback modes
- Request logging now includes structured data with automatic PII redaction
- CORS configuration now properly restricts origins in production

### Security
- PII data (tokens, passwords, emails, phone numbers) automatically redacted from logs
- Security headers added to all responses
- CORS restricted to explicitly allowed origins
- JWT token validation enhanced with proper error handling

### Dependencies
- Added `redis>=4.0.0` for Redis-backed auth store
- Added `structlog>=23.0.0` for structured logging
- Added `fakeredis>=2.0.0` for testing without Redis dependency
- Added `respx>=0.20.0` for HTTP mocking in tests

### Deployment
- Azure App Service configuration optimized for production scaling
- Deployment testing and validation added to CI/CD pipeline
- Application Insights integration for production monitoring
- Automatic deployment logs with retention policy

### Testing
- 95%+ test coverage for new components
- End-to-end authentication flow testing
- Error handling and edge case coverage
- Performance and scalability testing scenarios
