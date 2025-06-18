targetScope = 'tenant'
extension microsoftGraphV1

@description('OAuth app display name')
param oauthAppDisplayName string = 'Telnyx MCP Server'

@description('Environment name')
param environmentName string

@description('Redirect URIs for all environments')
param redirectUris array = [
  'https://app-telnyxmcp-${environmentName}-eus2-001.azurewebsites.net/auth/callback'
]

// OAuth app configuration
var oauthAppName = 'telnyx-mcp-server' // Shared across all environments

// Create OAuth app registration
resource app 'Microsoft.Graph/applications@v1.0' = {
  uniqueName: oauthAppName
  displayName: oauthAppDisplayName
  signInAudience: 'AzureADMyOrg'
  web: {
    redirectUris: redirectUris
    implicitGrantSettings: {
      enableIdTokenIssuance: true
      enableAccessTokenIssuance: false
    }
  }
  requiredResourceAccess: [
    {
      resourceAppId: '00000003-0000-0000-c000-000000000000' // Microsoft Graph
      resourceAccess: [
        {
          id: 'e1fe6dd8-ba31-4d61-89e7-88639da4683d' // User.Read
          type: 'Scope'
        }
        {
          id: '37f7f235-527c-4136-accd-4a02d197296e' // openid
          type: 'Scope'
        }
        {
          id: '14dad69e-099b-42c9-810b-d002981feec1' // profile
          type: 'Scope'
        }
      ]
    }
  ]
}

// Create service principal for the app
resource servicePrincipal 'Microsoft.Graph/servicePrincipals@v1.0' = {
  appId: app.appId
  displayName: oauthAppDisplayName
}

// Grant OAuth2 permissions to the app for all users in the tenant
var graphAppId = '00000003-0000-0000-c000-000000000000'

// Get the Microsoft Graph service principal
resource msGraphSP 'Microsoft.Graph/servicePrincipals@v1.0' existing = {
  appId: graphAppId
}

// Grant permissions
resource oauthPermissionGrant 'Microsoft.Graph/oauth2PermissionGrants@v1.0' = {
  clientId: servicePrincipal.id
  resourceId: msGraphSP.id
  consentType: 'AllPrincipals'
  scope: 'User.Read openid profile'
}

output appId string = app.appId
output objectId string = app.id
output servicePrincipalId string = servicePrincipal.id
output displayName string = app.displayName
