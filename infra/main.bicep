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

// Create managed identity for deployment scripts
module managedIdentity './core/identity/managed-identity.bicep' = if (createOAuthApp && useKeyVault) {
  name: 'managed-identity'
  scope: rg
  params: {
    name: '${abbrs.managedIdentityUserAssignedIdentities}${workloadName}-${environment}-${locationShortName}-001'
    location: location
    tags: tags
    keyVaultName: keyVault.outputs.name
  }
}

// Generate certificate for OAuth app
module certificate './core/identity/certificate-generator.bicep' = if (createOAuthApp && useKeyVault) {
  name: 'certificate-generator'
  scope: rg
  params: {
    keyVaultName: keyVault.outputs.name
    certificateName: 'oauth-app-cert'
    subjectName: 'CN=TelnyxMCPServer'
    managedIdentityId: managedIdentity.outputs.id
    location: location
    tags: tags
  }
  dependsOn: [
    roleWait  // Ensure role assignments have propagated
  ]
}

// OAuth app configuration
var oauthAppName = 'telnyx-mcp-server' // Shared across all environments
var currentEnvRedirectUri = 'https://${abbrs.webSitesAppService}${workloadName}-${environment}-${locationShortName}-001.azurewebsites.net/auth/callback'

// Create OAuth app registration with certificate
// Microsoft Graph resources require tenant scope when called from subscription-scoped template
module oauthApp './core/identity/oauth-app.bicep' = if (createOAuthApp) {
  name: 'oauth-app'
  scope: tenant()
  params: {
    appName: oauthAppName // Same name across all environments
    displayName: oauthAppDisplayName
    redirectUris: [
      currentEnvRedirectUri
      // The module will merge with existing redirect URIs
    ]
    enableIdToken: true
    enableAccessToken: false
    certKey: useKeyVault ? certificate.outputs.certKey : ''
    certThumbprint: useKeyVault ? certificate.outputs.certThumbprint : ''
    certStart: useKeyVault ? certificate.outputs.certStart : ''
    certEnd: useKeyVault ? certificate.outputs.certEnd : ''
  }
}

// Grant OAuth permissions
module oauthPermissions './core/identity/oauth-permissions.bicep' = if (createOAuthApp) {
  name: 'oauth-permissions'
  scope: tenant()
  params: {
    oauthServicePrincipalId: oauthApp.outputs.servicePrincipalId
    scopes: 'User.Read openid profile'
  }
}

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

// Grant App Service access to Key Vault for certificate operations
// This MUST complete before any web certificates can be created
module appServiceKeyVaultAccess './core/security/keyvault-app-service-access.bicep' = if (useKeyVault) {
  name: 'app-service-keyvault-access'
  scope: rg
  params: {
    keyVaultName: keyVault.outputs.name
  }
  dependsOn: [
    keyVault
  ]
}

// Add a deployment script to ensure role propagation
module roleWait './core/identity/wait-script.bicep' = if (useKeyVault) {
  name: 'role-propagation-wait'
  scope: rg
  params: {
    location: location
    tags: tags
  }
  dependsOn: [
    managedIdentity  // Wait for managed identity and its role assignments
    appServiceKeyVaultAccess  // Wait for app service role assignment
  ]
}

// Web certificate for OAuth authentication - deployed at RG scope via module
module webCert './core/security/web-certificate.bicep' = if (createOAuthApp && useKeyVault) {
  name: 'web-certificate'
  scope: rg
  params: {
    certificateName: 'oauth-app-cert'
    location: location
    keyVaultId: keyVault.outputs.id
    keyVaultSecretName: 'oauth-app-cert'
    tags: tags
  }
  dependsOn: [
    certificate  // Ensure certificate is created first
    roleWait  // Ensure role assignments have propagated
  ]
}

// Runtime thumbprint for app settings
var certThumbprint = createOAuthApp && useKeyVault ? webCert.outputs.thumbprint : ''

// The application frontend
module web './app/web.bicep' = {
  name: 'web'
  scope: rg
  params: {
    name: '${abbrs.webSitesAppService}${workloadName}-${environment}-${locationShortName}-001'
    location: location
    tags: tags
    appServicePlanId: appServicePlan.outputs.id
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
      AZURE_CLIENT_ID: createOAuthApp ? oauthApp.outputs.appId : existingOauthAppClientId
      AZURE_TENANT_ID: tenant().tenantId
      AZURE_REDIRECT_URI: currentEnvRedirectUri
      AZURE_CERTIFICATE_THUMBPRINT: certThumbprint

      // Tell App Service to load the certificate
      WEBSITE_LOAD_CERTIFICATES: certThumbprint

      // JWT Configuration
      JWT_SECRET_KEY: useKeyVault ? '@Microsoft.KeyVault(VaultName=${keyVault.outputs.name};SecretName=jwt-secret-key)' : jwtSecretKey
      JWT_ALGORITHM: 'HS256'
      JWT_EXPIRATION_HOURS: '24'

      // Telnyx Configuration
      TELNYX_API_KEY: useKeyVault ? '@Microsoft.KeyVault(VaultName=${keyVault.outputs.name};SecretName=telnyx-api-key)' : telnyxApiKey


      // Environment and Logging
      ENVIRONMENT: environment
      LOG_LEVEL: environment == 'prod' ? 'WARNING' : environment == 'staging' ? 'INFO' : 'DEBUG'
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
      WEBSITE_RUN_FROM_PACKAGE: '0'
      WEBSITES_CONTAINER_START_TIME_LIMIT: '1800'
      WEBSITES_ENABLE_APP_SERVICE_STORAGE: 'false'
      WEBSITE_WEBDEPLOY_USE_SCM: 'true'
    }
  }
}

// Grant web app access to Key Vault (conditional)
module webKeyVaultAccess './core/security/keyvault-access.bicep' = if (useKeyVault) {
  name: 'web-keyvault-access'
  scope: rg
  params: {
    keyVaultName: keyVault.outputs.name
    principalId: web.outputs.principalId
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
output OAUTH_APP_CLIENT_ID string = createOAuthApp ? oauthApp.outputs.appId : ''
output OAUTH_APP_OBJECT_ID string = createOAuthApp ? oauthApp.outputs.objectId : ''
output GITHUB_ACTIONS_CLIENT_ID string = createGitHubFIC ? githubFIC.outputs.appId : ''
output GITHUB_ACTIONS_TENANT_ID string = tenant().tenantId
output GITHUB_ACTIONS_SUBSCRIPTION_ID string = subscription().subscriptionId
