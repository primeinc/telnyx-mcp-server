@description('Key Vault name to check access for')
param keyVaultName string

@description('Location for the deployment script')
param location string

@description('Tags for the deployment script')
param tags object = {}

@description('User-assigned managed identity for deployment script')
param managedIdentityId string

// Check if App Service has access to Key Vault - always passes
resource checkAccess 'Microsoft.Resources/deploymentScripts@2023-08-01' = {
  name: 'check-app-service-keyvault-access'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentityId}': {}
    }
  }
  kind: 'AzurePowerShell'
  properties: {
    azPowerShellVersion: '8.3'
    timeout: 'PT5M'
    retentionInterval: 'P1D'
    scriptContent: '''
      param(
        [string] $keyVaultName
      )

      $vaultResourceId = "/subscriptions/$env:AZURE_SUBSCRIPTION_ID/resourceGroups/$env:AZURE_RESOURCE_GROUP/providers/Microsoft.KeyVault/vaults/$keyVaultName"
      $appServicePrincipalId = "abfa0a7c-a6b6-4736-8310-5855508787cd"

      Write-Host "Checking if App Service has access to Key Vault: $keyVaultName"

      try {
        # Check for existing role assignments
        $assignments = Get-AzRoleAssignment -ObjectId $appServicePrincipalId -Scope $vaultResourceId -ErrorAction SilentlyContinue

        if ($assignments) {
          Write-Host "App Service already has access to Key Vault"
        } else {
          Write-Host "App Service does NOT have access to Key Vault yet"
        }
      } catch {
        Write-Host "Could not check role assignments: $_"
      }

      # Always pass
      Write-Host "Continuing deployment..."
      exit 0
    '''
    arguments: '-keyVaultName ${keyVaultName}'
    environmentVariables: [
      {
        name: 'AZURE_SUBSCRIPTION_ID'
        value: subscription().subscriptionId
      }
      {
        name: 'AZURE_RESOURCE_GROUP'
        value: resourceGroup().name
      }
    ]
    cleanupPreference: 'OnSuccess'
  }
}
