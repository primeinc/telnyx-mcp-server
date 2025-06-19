@description('Location for the deployment script')
param location string

@description('Tags for the deployment script')
param tags object = {}

// Simple deployment script to wait for role assignments to propagate
resource waitScript 'Microsoft.Resources/deploymentScripts@2023-08-01' = {
  name: 'wait-for-role-propagation'
  location: location
  tags: tags
  kind: 'AzurePowerShell'
  properties: {
    azPowerShellVersion: '8.3'
    timeout: 'PT5M'
    scriptContent: '''
      Write-Host "Waiting for role assignments to propagate..."
      Start-Sleep -Seconds 30
      Write-Host "Role propagation wait complete."
    '''
    retentionInterval: 'PT1H'
    cleanupPreference: 'OnSuccess'
  }
}
