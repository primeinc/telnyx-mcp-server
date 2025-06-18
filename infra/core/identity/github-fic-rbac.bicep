@description('Service principal ID of the GitHub Actions app')
param servicePrincipalId string

@description('Resource group to grant access to')
param resourceGroupId string = resourceGroup().id

// Assign contributor role to the service principal
resource contributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroupId, servicePrincipalId, 'github-actions-contributor')
  properties: {
    principalId: servicePrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b24988ac-6180-42a0-ab88-20f7382dd24c') // Contributor
    principalType: 'ServicePrincipal'
  }
}

output roleAssignmentId string = contributorRole.id
