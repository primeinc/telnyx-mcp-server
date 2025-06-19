param keyVaultName string
param principalId string

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

// Add access policy for the principal
resource accessPolicy 'Microsoft.KeyVault/vaults/accessPolicies@2023-07-01' = {
  name: 'add'
  parent: keyVault
  properties: {
    accessPolicies: [
      {
        tenantId: tenant().tenantId
        objectId: principalId
        permissions: {
          secrets: ['get', 'list']
          certificates: ['get', 'list']
        }
      }
    ]
  }
}
