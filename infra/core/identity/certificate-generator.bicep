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
      $ErrorActionPreference = 'Continue'
      $DeploymentScriptOutputs = @{}

      # First just check if certificate exists without loading it
      try {
        $certList = Get-AzKeyVaultCertificate -VaultName $vaultName -ErrorAction SilentlyContinue
        $existingCert = $certList | Where-Object { $_.Name -eq $certificateName }
      } catch {
        Write-Host "Could not list certificates: $_"
        $existingCert = $null
      }
      if ($existingCert) {
        Write-Host \"Certificate $certificateName already exists in vault $vaultName.\"

        # Get the actual certificate details
        $fullCert = Get-AzKeyVaultCertificate -VaultName $vaultName -Name $certificateName

        # The public key is in the Certificate property
        $publicKey = [System.Convert]::ToBase64String($fullCert.Certificate.GetRawCertData())

        $DeploymentScriptOutputs['certStart'] = $fullCert.Certificate.NotBefore.ToString('yyyy-MM-ddTHH:mm:ss')
        $DeploymentScriptOutputs['certEnd'] = $fullCert.Certificate.NotAfter.ToString('yyyy-MM-ddTHH:mm:ss')
        $DeploymentScriptOutputs['certThumbprint'] = $fullCert.Thumbprint
        $DeploymentScriptOutputs['certKey'] = $publicKey

        Write-Host "Returning existing certificate info with thumbprint: $($fullCert.Thumbprint)"
        exit 0
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

        # Decode and load the certificate - Key Vault certs have no password
        $certBytes = [Convert]::FromBase64String($certValue)
        # Use different constructor that doesn't require password for Linux compatibility
        $pfxCert = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($certBytes)

        # Get the public key
        $publicKey = [System.Convert]::ToBase64String($pfxCert.GetRawCertData())

        $DeploymentScriptOutputs['certStart'] = $newCert.Certificate.NotBefore.ToString('yyyy-MM-ddTHH:mm:ss')
        $DeploymentScriptOutputs['certEnd'] = $newCert.Certificate.NotAfter.ToString('yyyy-MM-ddTHH:mm:ss')
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
