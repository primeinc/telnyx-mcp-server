param name string
param location string = resourceGroup().location
param tags object = {}

// App Service Plan ID
param appServicePlanId string

// Certificate loading is handled automatically by WEBSITE_LOAD_CERTIFICATES in app settings

// App Settings
@secure()
param appSettings object = {}

// Application Insights connection string is passed via appSettings from main.bicep
// No need to reference the resource directly

// Authentication parameters for Built-in Auth
@description('The client ID of the Microsoft Entra application')
param authClientId string = ''

@description('Enable Built-in Authentication')
param enableBuiltInAuth bool = false

// Web App
resource web 'Microsoft.Web/sites@2022-03-01' = {
  name: name
  location: location
  tags: union(tags, { 'azd-service-name': 'web' })
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: appServicePlanId
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.11'
      alwaysOn: true
      ftpsState: 'FtpsOnly'
      minTlsVersion: '1.2'
      scmMinTlsVersion: '1.2'
      healthCheckPath: '/health'
      // Startup command for Gunicorn with Uvicorn worker
      appCommandLine: 'gunicorn -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --timeout 600 --access-logfile - --error-logfile - --log-level debug telnyx_mcp_server.remote.server:app'
      // loadCertificates is Windows-only, not needed for Linux App Service
      appSettings: [for setting in items(appSettings): {
        name: setting.key
        value: setting.value
      }]
    }
  }
}

// Enable logging
resource webLogs 'Microsoft.Web/sites/config@2022-03-01' = {
  parent: web
  name: 'logs'
  properties: {
    applicationLogs: {
      fileSystem: {
        level: 'Information'
      }
    }
    detailedErrorMessages: {
      enabled: true
    }
    failedRequestsTracing: {
      enabled: true
    }
    httpLogs: {
      fileSystem: {
        enabled: true
        retentionInDays: 1
        retentionInMb: 35
      }
    }
  }
}

// Configure Built-in Authentication (Easy Auth) with Federated Identity Credentials
resource configAuth 'Microsoft.Web/sites/config@2022-03-01' = if (enableBuiltInAuth) {
  parent: web
  name: 'authsettingsV2'
  properties: {
    globalValidation: {
      requireAuthentication: true
      unauthenticatedClientAction: 'RedirectToLoginPage'
      redirectToProvider: 'azureactivedirectory'
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: authClientId
          // This special value tells Azure to use managed identity with FIC
          clientSecretSettingName: 'OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID'
          openIdIssuer: '${environment().authentication.loginEndpoint}${tenant().tenantId}/v2.0'
        }
        validation: {
          defaultAuthorizationPolicy: {
            allowedApplications: []
          }
        }
      }
    }
    login: {
      tokenStore: {
        enabled: true
      }
    }
  }
}

output uri string = 'https://${web.properties.defaultHostName}'
output name string = web.name
output principalId string = web.identity.principalId
