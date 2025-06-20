param appServiceName string

@description('The client ID of the Microsoft Entra application.')
param clientId string

param openIdIssuer string

resource appService 'Microsoft.Web/sites@2022-03-01' existing = {
  name: appServiceName
}

resource configAuth 'Microsoft.Web/sites/config@2022-03-01' = {
  parent: appService
  name: 'authsettingsV2'
  properties: {
    platform: {
      enabled: true
      runtimeVersion: '~1'
    }
    globalValidation: {
      requireAuthentication: true
      unauthenticatedClientAction: 'RedirectToLoginPage'
      redirectToProvider: 'azureactivedirectory'
      excludedPaths: [
        '/.well-known/oauth-protected-resource'
        '/.well-known/oauth-authorization-server'
        '/.well-known/mcp-oauth-metadata'
        '/.well-known/openid-configuration'
        '/health'
        '/docs'
        '/openapi.json'
        '/register'
      ]
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: clientId
          clientSecretSettingName: 'OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID'
          openIdIssuer: openIdIssuer
        }
        validation: {
          defaultAuthorizationPolicy: {
            allowedApplications: []
          }
        }
      }
      apple: {
        enabled: false
      }
      facebook: {
        enabled: false
      }
      gitHub: {
        enabled: false
      }
      google: {
        enabled: false
      }
      legacyMicrosoftAccount: {
        enabled: false
      }
      twitter: {
        enabled: false
      }
    }
    login: {
      tokenStore: {
        enabled: true
      }
    }
  }
}
