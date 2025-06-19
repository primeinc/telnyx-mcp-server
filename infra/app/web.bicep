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

output uri string = 'https://${web.properties.defaultHostName}'
output name string = web.name
output principalId string = web.identity.principalId
