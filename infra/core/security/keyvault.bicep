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

output id string = keyVault.id
output name string = keyVault.name
output uri string = keyVault.properties.vaultUri
