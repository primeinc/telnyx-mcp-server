param keyVaultName string
param principalId string

param permissions object = {
  secrets: ['get', 'list']
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource accessPolicy 'Microsoft.KeyVault/vaults/accessPolicies@2023-07-01' = {
  parent: keyVault
  name: 'add'
  properties: {
    accessPolicies: [
      {
        objectId: principalId
        tenantId: tenant().tenantId
        permissions: permissions
      }
    ]
  }
}
