extension microsoftGraphV1

targetScope = 'tenant'

@description('Unique name for the application')
param appName string

@description('Display name for the application')
param displayName string

@description('Redirect URIs for the application')
param redirectUris array = []

@description('Enable ID token issuance')
param enableIdToken bool = true

@description('Enable access token issuance')
param enableAccessToken bool = false

@description('Certificate public key for authentication')
param certKey string

@description('Certificate thumbprint')
param certThumbprint string

@description('Certificate start date')
param certStart string

@description('Certificate end date')
param certEnd string

// Create the app registration with certificate authentication
resource app 'Microsoft.Graph/applications@v1.0' = {
  uniqueName: appName
  displayName: displayName
  signInAudience: 'AzureADMyOrg'
  web: {
    redirectUris: redirectUris
    implicitGrantSettings: {
      enableIdTokenIssuance: enableIdToken
      enableAccessTokenIssuance: enableAccessToken
    }
  }
  keyCredentials: [
    {
      displayName: 'Certificate from Key Vault'
      usage: 'Verify'
      type: 'AsymmetricX509Cert'
      key: certKey
      startDateTime: certStart
      endDateTime: certEnd
    }
  ]
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
  displayName: displayName
}

output appId string = app.appId
output objectId string = app.id
output servicePrincipalId string = servicePrincipal.id
output displayName string = app.displayName
output certThumbprint string = certThumbprint
