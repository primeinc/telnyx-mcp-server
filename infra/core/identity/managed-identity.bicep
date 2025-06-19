@description('Name of the managed identity')
param name string

@description('Location for the managed identity')
param location string = resourceGroup().location

@description('Tags for the managed identity')
param tags object = {}

// Create user-assigned managed identity
resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: name
  location: location
  tags: tags
}

@description('Name of the Key Vault')
param keyVaultName string

// Reference to existing Key Vault
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

// Grant the managed identity RBAC roles for Key Vault
var keyVaultSecretsUserRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
var keyVaultCertificatesOfficerRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'a4417e6f-fecd-4de8-b567-7b0420556985')

// Use the principalId in the GUID to ensure uniqueness
resource secretsRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, managedIdentity.properties.principalId, keyVaultSecretsUserRole)
  scope: keyVault
  properties: {
    roleDefinitionId: keyVaultSecretsUserRole
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource certificatesRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, managedIdentity.properties.principalId, keyVaultCertificatesOfficerRole)
  scope: keyVault
  properties: {
    roleDefinitionId: keyVaultCertificatesOfficerRole
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

output id string = managedIdentity.id
output principalId string = managedIdentity.properties.principalId
output clientId string = managedIdentity.properties.clientId
