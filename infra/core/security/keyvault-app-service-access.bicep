param keyVaultName string

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

// Grant Microsoft Azure App Service access for certificate operations
// This is required for App Service to import certificates from Key Vault
var azureAppServicePrincipalId = 'abfa0a7c-a6b6-4736-8310-5855508787cd' // Global Microsoft Azure App Service principal
var keyVaultSecretsUserRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')

resource appServiceRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, azureAppServicePrincipalId, 'app-service-cert-access')
  scope: keyVault
  properties: {
    roleDefinitionId: keyVaultSecretsUserRole
    principalId: azureAppServicePrincipalId
    principalType: 'ServicePrincipal'
  }
}
