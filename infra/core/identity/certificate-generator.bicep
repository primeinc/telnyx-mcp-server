@description('Key Vault name where certificate will be stored')
param keyVaultName string

@description('Certificate name')
param certificateName string

@description('Certificate subject name')
param subjectName string

@description('User-assigned managed identity for deployment script')
param managedIdentityId string

@description('Location for deployment script')
param location string = resourceGroup().location

@description('Current UTC time for force update')
param utcValue string = utcNow()

@description('Resource tags')
param tags object = {}

// Deployment script to create certificate in Key Vault
resource createCertificate 'Microsoft.Resources/deploymentScripts@2023-08-01' = {
  name: 'createCertificate-${certificateName}'
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
    forceUpdateTag: utcValue
    azPowerShellVersion: '8.3'
    timeout: 'PT30M'
    arguments: '-vaultName ${keyVaultName} -certificateName ${certificateName} -subjectName ${subjectName}'
    scriptContent: '''
      param(
        [string] [Parameter(Mandatory=$true)] $vaultName,
        [string] [Parameter(Mandatory=$true)] $certificateName,
        [string] [Parameter(Mandatory=$true)] $subjectName
      )
      $ErrorActionPreference = 'Stop'
      $DeploymentScriptOutputs = @{}

      $existingCert = Get-AzKeyVaultCertificate -VaultName $vaultName -Name $certificateName
      if ($existingCert -and $existingCert.Certificate.Subject -eq $subjectName) {
        Write-Host \"Certificate $certificateName in vault $vaultName is already present.\"

        # Get the secret value
        $certSecret = Get-AzKeyVaultSecret -VaultName $vaultName -Name $certificateName
        $certValue = $certSecret.SecretValue | ConvertFrom-SecureString -AsPlainText

        # Decode and load the certificate
        $certBytes = [Convert]::FromBase64String($certValue)
        $pfxCert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2 -ArgumentList $certBytes, \"\", ([System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::Exportable)

        # Get the public key
        $publicKey = [System.Convert]::ToBase64String($pfxCert.GetRawCertData())

        $DeploymentScriptOutputs['certStart'] = $existingCert.notBefore
        $DeploymentScriptOutputs['certEnd'] = $existingCert.expires
        $DeploymentScriptOutputs['certThumbprint'] = $existingCert.Thumbprint
        $DeploymentScriptOutputs['certKey'] = $publicKey
      }
      else {
        $policy = New-AzKeyVaultCertificatePolicy -SubjectName $subjectName -IssuerName Self -ValidityInMonths 24 -Verbose
        Add-AzKeyVaultCertificate -VaultName $vaultName -Name $certificateName -CertificatePolicy $policy -Verbose

        $tries = 0
        do {
          Write-Host 'Waiting for certificate creation completion...'
          Start-Sleep -Seconds 10
          $operation = Get-AzKeyVaultCertificateOperation -VaultName $vaultName -Name $certificateName
          $tries++
          if ($operation.Status -eq 'failed') {
            throw 'Creating certificate $certificateName in vault $vaultName failed with error $($operation.ErrorMessage)'
          }
          if ($tries -gt 120) {
            throw 'Timed out waiting for creation of certificate $certificateName in vault $vaultName'
          }
        } while ($operation.Status -ne 'completed')

        $newCert = Get-AzKeyVaultCertificate -VaultName $vaultName -Name $certificateName

        # Get the secret value
        $certSecret = Get-AzKeyVaultSecret -VaultName $vaultName -Name $certificateName
        $certValue = $certSecret.SecretValue | ConvertFrom-SecureString -AsPlainText

        # Decode and load the certificate
        $certBytes = [Convert]::FromBase64String($certValue)
        $pfxCert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2 -ArgumentList $certBytes, \"\", ([System.Security.Cryptography.X509Certificates.X509KeyStorageFlags]::Exportable)

        # Get the public key
        $publicKey = [System.Convert]::ToBase64String($pfxCert.GetRawCertData())

        $DeploymentScriptOutputs['certStart'] = $newCert.notBefore
        $DeploymentScriptOutputs['certEnd'] = $newCert.expires
        $DeploymentScriptOutputs['certThumbprint'] = $newCert.Thumbprint
        $DeploymentScriptOutputs['certKey'] = $publicKey
      }
    '''
    cleanupPreference: 'OnSuccess'
    retentionInterval: 'P1D'
  }
}

output certKey string = createCertificate.properties.outputs.certKey
output certThumbprint string = createCertificate.properties.outputs.certThumbprint
output certStart string = createCertificate.properties.outputs.certStart
output certEnd string = createCertificate.properties.outputs.certEnd
