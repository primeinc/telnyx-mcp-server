param certificateName string
param location string
param keyVaultId string
param keyVaultSecretName string
param serverFarmId string
param tags object = {}

// Web certificate for OAuth authentication
resource webCertificate 'Microsoft.Web/certificates@2022-03-01' = {
  name: certificateName
  location: location
  tags: tags
  properties: {
    keyVaultId: keyVaultId
    keyVaultSecretName: keyVaultSecretName
    serverFarmId: serverFarmId
  }
}

output name string = webCertificate.name
output thumbprint string = webCertificate.properties.thumbprint
