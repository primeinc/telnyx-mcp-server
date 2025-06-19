@description('Key Vault name to check access for')
param keyVaultName string

@description('Location for the deployment script')
param location string

@description('Tags for the deployment script')
param tags object = {}

// Check if App Service has access to Key Vault
resource checkAccess 'Microsoft.Resources/deploymentScripts@2023-08-01' = {
  name: 'check-app-service-keyvault-access'
  location: location
  tags: tags
  kind: 'AzurePowerShell'
  properties: {
    azPowerShellVersion: '8.3'
    timeout: 'PT5M'
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
          $hasAccess = $true
        } else {
          Write-Host "App Service does NOT have access to Key Vault"
          $hasAccess = $false
        }
      } catch {
        Write-Host "Could not check role assignments: $_"
        $hasAccess = $false
      }

      # Output result
      $DeploymentScriptOutputs = @{}
      $DeploymentScriptOutputs['hasAccess'] = $hasAccess
      $DeploymentScriptOutputs['checked'] = $true
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
    retentionInterval: 'PT1H'
    cleanupPreference: 'OnSuccess'
  }
}

output hasAccess bool = checkAccess.properties.outputs.hasAccess
output checked bool = checkAccess.properties.outputs.checked
