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

output id string = managedIdentity.id
output principalId string = managedIdentity.properties.principalId
output clientId string = managedIdentity.properties.clientId
