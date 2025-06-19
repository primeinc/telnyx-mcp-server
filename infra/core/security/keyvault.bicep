param name string
param location string = resourceGroup().location
param tags object = {}

@description('Enable purge protection to prevent permanent deletion of secrets')
param enablePurgeProtection bool = false

@description('Enable soft delete with retention period')
param softDeleteRetentionInDays int = 90

@description('Enable RBAC authorization instead of access policies')
param enableRbacAuthorization bool = true

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: name
  location: location
  tags: tags
  properties: union({
    tenantId: tenant().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enabledForDeployment: false
    enabledForDiskEncryption: false
    enabledForTemplateDeployment: true
    enableSoftDelete: true
    softDeleteRetentionInDays: softDeleteRetentionInDays
    enableRbacAuthorization: enableRbacAuthorization
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Allow'
    }
  }, enablePurgeProtection ? {
    enablePurgeProtection: true
  } : {})
}

// Grant Microsoft Azure App Service access for certificate operations
// This is required for App Service to import certificates from Key Vault
var azureAppServicePrincipalId = 'abfa0a7c-a6b6-4736-8310-5855508787cd' // Global Microsoft Azure App Service principal
var keyVaultSecretsUserRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')

resource appServiceRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (enableRbacAuthorization) {
  name: guid(keyVault.id, azureAppServicePrincipalId, 'app-service-access')
  scope: keyVault
  properties: {
    roleDefinitionId: keyVaultSecretsUserRole
    principalId: azureAppServicePrincipalId
    principalType: 'ServicePrincipal'
  }
}

output id string = keyVault.id
output name string = keyVault.name
output uri string = keyVault.properties.vaultUri
