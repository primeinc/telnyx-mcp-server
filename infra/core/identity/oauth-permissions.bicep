extension microsoftGraphV1

targetScope = 'tenant'

@description('Service principal ID of the OAuth app')
param oauthServicePrincipalId string

@description('Scopes to grant (space-separated)')
param scopes string = 'User.Read openid profile'

// Microsoft Graph constants
var graphAppId = '00000003-0000-0000-c000-000000000000'

// Get the Microsoft Graph service principal
resource msGraphSP 'Microsoft.Graph/servicePrincipals@v1.0' existing = {
  appId: graphAppId
}

// Grant OAuth2 permissions to the app for all users in the tenant
resource oauthPermissionGrant 'Microsoft.Graph/oauth2PermissionGrants@v1.0' = {
  clientId: oauthServicePrincipalId
  resourceId: msGraphSP.id
  consentType: 'AllPrincipals'
  scope: scopes
}

output grantedScopes string = oauthPermissionGrant.scope
output grantId string = oauthPermissionGrant.id
