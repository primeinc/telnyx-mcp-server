extension microsoftGraphV1

targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('Name of the environment that can be used as part of naming resource convention')
param environmentName string

@minLength(1)
@description('Primary location for all resources')
param location string


// OAuth and application configuration parameters
@description('Create OAuth app registration automatically')
param createOAuthApp bool = true

@description('OAuth app display name')
param oauthAppDisplayName string = 'Telnyx MCP Server'

@description('GitHub organization or username for FIC')
param gitHubOwner string = ''

@description('GitHub repository name for FIC')
param gitHubRepo string = ''

@description('Create GitHub Actions FIC')
param createGitHubFIC bool = !empty(gitHubOwner) && !empty(gitHubRepo)

@description('Existing OAuth App Client ID (used when createOAuthApp is false)')
param existingOauthAppClientId string = ''

@secure()
@description('JWT Secret Key for token signing')
param jwtSecretKey string = ''

@secure()
@description('Telnyx API Key')
param telnyxApiKey string = ''

@description('Application Environment')
@allowed(['dev', 'staging', 'prod'])
param environment string = 'prod'

@description('Use Azure Key Vault for secret management')
param useKeyVault bool = true

@description('Deploy Redis cache for session storage')
param useRedis bool = true

// Tagging parameters
@description('Data classification for the workload')
@allowed(['Non-business', 'Public', 'General', 'Confidential', 'Highly confidential'])
param dataClassification string = 'General'

@description('Business criticality of the workload')
@allowed(['Low', 'Medium', 'High', 'Business unit-critical', 'Mission-critical'])
param businessCriticality string = 'High'

@description('Business unit that owns the workload')
param businessUnit string = 'Engineering'

@description('Team responsible for day-to-day operations')
param opsTeam string = 'Cloud operations'

// Optional parameters to override the default azd resource naming conventions
param resourceGroupName string = ''

var abbrs = loadJsonContent('./abbreviations.json')
// Resource token not needed - using deterministic naming with workloadName-environment-location
// var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))

// Tags based on Microsoft's recommendations
var tags = {
  'azd-env-name': environmentName
  env: environment
  owner: 'will.peters'
  costCenter: 'telnyx-mcp'
  WorkloadName: workloadName
  Environment: environment
  DataClassification: dataClassification
  Criticality: businessCriticality
  BusinessUnit: businessUnit
  OpsCommitment: environment == 'prod' ? 'Platform operations' : 'Baseline only'
  OpsTeam: opsTeam
  ProjectName: 'Telnyx MCP Server'
  CostCenter: '${businessUnit}-${environment}'
}

// Naming convention components
var workloadName = 'telnyxmcp' // Shortened for resource naming constraints
var locationShortName = contains(abbrs, 'locations') && contains(abbrs.locations, location) ? abbrs.locations[location] : location

// Create resource group
resource rg 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: !empty(resourceGroupName) ? resourceGroupName : '${abbrs.resourcesResourceGroups}${workloadName}-${environment}-001'
  location: location
  tags: tags
}

// REMOVED: Certificate-based authentication modules
// We now use Built-in Auth with Federated Identity Credentials (no certificates needed)

// OAuth app configuration
var oauthAppName = 'telnyx-mcp-server' // Shared across all environments

// Create GitHub Actions FIC - App registration at tenant scope
module githubFIC './core/identity/github-fic-app.bicep' = if (createGitHubFIC) {
  name: 'github-fic-app'
  scope: tenant()
  params: {
    gitHubOwner: gitHubOwner
    gitHubRepo: gitHubRepo
    displayName: 'GitHub Actions - Telnyx MCP Server'
    appName: 'github-actions-telnyx-mcp' // Shared across environments
  }
}

// Grant GitHub Actions contributor access to resource group
module githubRBAC './core/identity/github-fic-rbac.bicep' = if (createGitHubFIC) {
  name: 'github-fic-rbac'
  scope: rg
  params: {
    servicePrincipalId: githubFIC.outputs.servicePrincipalId
  }
}

// App Service access is now handled via access policies in the Key Vault module

// REMOVED: These modules are not needed for Linux App Service
// - checkAppServiceAccess: Not needed, managed identity access is handled by keyvault-access.bicep
// - roleWait: Not needed, Azure handles role propagation automatically with proper dependencies
// - webCert: Not needed for Linux App Service - certificates are loaded directly from Key Vault in code

// REMOVED: Certificate thumbprint no longer needed with Built-in Auth

// Create user-assigned managed identity for Built-in Auth with FIC
// This is required for the OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID pattern
module webIdentity './core/identity/managed-identity.bicep' = {
  name: 'web-identity'
  scope: rg
  params: {
    name: '${abbrs.webSitesAppService}${workloadName}-identity'
    location: location
    tags: tags
  }
}

// The application frontend
module web './app/web.bicep' = {
  name: 'web'
  scope: rg
  params: {
    name: '${abbrs.webSitesAppService}${workloadName}-${environment}-${locationShortName}-001'
    location: location
    tags: tags
    appServicePlanId: appServicePlan.outputs.id
    enableBuiltInAuth: !empty(existingOauthAppClientId)  // Only enable if we have an OAuth app
    authClientId: existingOauthAppClientId
    userAssignedIdentityId: webIdentity.outputs.id
    userAssignedIdentityClientId: webIdentity.outputs.clientId
    appSettings: {
      // Application Insights
      APPLICATIONINSIGHTS_CONNECTION_STRING: monitoring.outputs.applicationInsightsConnectionString
      ApplicationInsightsAgent_EXTENSION_VERSION: '~3'
      XDT_MicrosoftApplicationInsights_Mode: 'recommended'
      APPLICATION_INSIGHTS_KEY: monitoring.outputs.applicationInsightsInstrumentationKey

      // Key Vault Configuration
      AZURE_KEY_VAULT_ENDPOINT: useKeyVault ? keyVault.outputs.uri : ''
      USE_KEY_VAULT: useKeyVault ? 'true' : 'false'

      // OAuth Configuration
      // Note: With Built-in Auth and FIC, the App Service doesn't need client secrets
      AZURE_CLIENT_ID: existingOauthAppClientId  // This must be provided or OAuth app created separately
      AZURE_TENANT_ID: tenant().tenantId
      AZURE_REDIRECT_URI: 'https://${abbrs.webSitesAppService}${workloadName}-${environment}-${locationShortName}-001.azurewebsites.net/auth/callback'
      // AZURE_CLIENT_SECRET is intentionally not set - we use managed identity with FIC

      // JWT Configuration
      JWT_SECRET_KEY: useKeyVault ? '@Microsoft.KeyVault(VaultName=${keyVault.outputs.name};SecretName=jwt-secret-key)' : jwtSecretKey
      JWT_ALGORITHM: 'HS256'
      JWT_EXPIRATION_HOURS: '24'

      // Telnyx Configuration
      TELNYX_API_KEY: useKeyVault ? '@Microsoft.KeyVault(VaultName=${keyVault.outputs.name};SecretName=telnyx-api-key)' : telnyxApiKey


      // Environment and Logging
      ENVIRONMENT: environment
      LOG_LEVEL: environment == 'prod' ? 'WARNING' : 'DEBUG'
      ENABLE_PII_REDACTION: environment == 'prod' ? 'true' : 'false'

      // Redis Configuration
      REDIS_URL: useRedis ? redis.outputs.connectionString : ''
      USE_REDIS: useRedis ? 'true' : 'false'

      // CORS and Security
      MCP_ALLOWED_ORIGINS: 'https://claude.ai,https://chat.anthropic.com'

      // Azure App Service Configuration
      SCM_DO_BUILD_DURING_DEPLOYMENT: 'true'
      ENABLE_ORYX_BUILD: 'true'
      PYTHON_ENABLE_GUNICORN_MULTIWORKERS: 'true'
      GUNICORN_CMD_ARGS: environment == 'prod' ? '--log-level warning' : environment == 'staging' ? '--log-level info' : '--log-level debug'
      WEBSITES_PORT: '8000'
      WEBSITE_RUN_FROM_PACKAGE: '1'  // Run directly from ZIP package
      Oryx_EnablePythonNixAlias: 'true'  // Create python -> python3 symlink
      WEBSITES_CONTAINER_START_TIME_LIMIT: '1800'
      WEBSITES_ENABLE_APP_SERVICE_STORAGE: 'false'
      WEBSITE_WEBDEPLOY_USE_SCM: 'true'
    }
  }
}

// Create OAuth app registration with Federated Identity Credential for Built-in Auth
// This replaces the old certificate-based authentication
module oauthAppFIC './core/identity/app-registration-fic.bicep' = if (createOAuthApp) {
  name: 'oauth-app-fic'
  scope: rg
  params: {
    clientAppName: '${oauthAppName}-${environment}'
    clientAppDisplayName: oauthAppDisplayName
    webAppEndpoint: 'https://${abbrs.webSitesAppService}${workloadName}-${environment}-${locationShortName}-001.azurewebsites.net'
    webAppIdentityId: webIdentity.outputs.principalId  // User-assigned managed identity principal ID
    issuer: '${az.environment().authentication.loginEndpoint}${tenant().tenantId}/v2.0'
  }
}

// Update web app with Built-in Auth configuration after OAuth app is created
module webAuthUpdate './core/identity/web-auth-update.bicep' = if (createOAuthApp) {
  name: 'web-auth-update'
  scope: rg
  params: {
    appServiceName: web.outputs.name
    clientId: oauthAppFIC.outputs.clientAppId
    openIdIssuer: '${az.environment().authentication.loginEndpoint}${tenant().tenantId}/v2.0'
  }
}


// Grant web app access to Key Vault (conditional)
module webKeyVaultAccess './core/security/keyvault-access.bicep' = if (useKeyVault) {
  name: 'web-keyvault-access'
  scope: rg
  params: {
    keyVaultName: keyVault.outputs.name
    principalId: webIdentity.outputs.principalId
  }
}

// Create an App Service Plan to group applications under the same payment plan and SKU
module appServicePlan './core/host/appserviceplan.bicep' = {
  name: 'appserviceplan'
  scope: rg
  params: {
    name: '${abbrs.webServerFarms}${workloadName}-${environment}-${locationShortName}-001'
    location: location
    tags: tags
    sku: {
      name: 'S1'  // Standard tier for production
      capacity: 1
    }
    kind: 'linux'
    reserved: true
  }
}

// Create Key Vault for secrets (conditional)
module keyVault './core/security/keyvault.bicep' = if (useKeyVault) {
  name: 'keyvault'
  scope: rg
  params: {
    // Key Vault names must be 3-24 characters, globally unique
    name: take('${abbrs.keyVaultVaults}${replace(workloadName, '-', '')}${environment}${uniqueString(rg.id)}', 24)
    location: location
    tags: tags
    enablePurgeProtection: environment == 'prod'
  }
}

// Store secrets in Key Vault (conditional)
module secrets './core/security/keyvault-secret.bicep' = [for secret in [
  { name: 'jwt-secret-key', value: jwtSecretKey }
  { name: 'telnyx-api-key', value: telnyxApiKey }
]: if (useKeyVault && !empty(secret.value)) {
  name: 'secret-${secret.name}'
  scope: rg
  params: {
    keyVaultName: keyVault.outputs.name
    name: secret.name
    value: secret.value
    tags: tags
  }
}]

// Monitor application with Azure Monitor
module monitoring './core/monitor/monitoring.bicep' = {
  name: 'monitoring'
  scope: rg
  params: {
    location: location
    tags: tags
    logAnalyticsName: '${abbrs.operationalInsightsWorkspaces}${workloadName}-${environment}-001'
    applicationInsightsName: '${abbrs.insightsComponents}${workloadName}-${environment}-001'
  }
}

// Redis cache for session storage and caching
module redis './core/cache/redis.bicep' = if (useRedis) {
  name: 'redis'
  scope: rg
  params: {
    name: '${abbrs.cacheRedis}${workloadName}-${environment}-001'
    location: location
    tags: tags
    skuName: 'Basic'
    skuFamily: 'C'
    skuCapacity: 0
  }
}

// Store Redis connection string in Key Vault
module redisSecret './core/security/keyvault-secret.bicep' = if (useKeyVault && useRedis) {
  name: 'secret-redis-connection-string'
  scope: rg
  params: {
    keyVaultName: keyVault.outputs.name
    name: 'redis-connection-string'
    value: redis.outputs.connectionString
    tags: tags
  }
}

// App outputs
output APPLICATIONINSIGHTS_CONNECTION_STRING string = monitoring.outputs.applicationInsightsConnectionString
output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = tenant().tenantId
output WEB_URI string = web.outputs.uri
output RESOURCE_GROUP string = rg.name
output AZURE_WEB_APP_NAME string = web.outputs.name
// Redis connection string is stored in Key Vault for security
output AZURE_KEY_VAULT_NAME string = useKeyVault ? keyVault.outputs.name : ''
output AZURE_KEY_VAULT_ENDPOINT string = useKeyVault ? keyVault.outputs.uri : ''
output OAUTH_APP_CLIENT_ID string = createOAuthApp ? oauthAppFIC.outputs.clientAppId : ''
output OAUTH_APP_OBJECT_ID string = createOAuthApp ? oauthAppFIC.outputs.clientAppObjectId : ''
output GITHUB_ACTIONS_CLIENT_ID string = createGitHubFIC ? githubFIC.outputs.appId : ''
output GITHUB_ACTIONS_TENANT_ID string = tenant().tenantId
output GITHUB_ACTIONS_SUBSCRIPTION_ID string = subscription().subscriptionId
