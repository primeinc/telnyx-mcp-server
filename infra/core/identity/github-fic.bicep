extension microsoftGraphV1

@description('GitHub organization or username')
param gitHubOwner string

@description('GitHub repository name')
param gitHubRepo string

@description('GitHub branch name')
param gitHubBranch string = 'main'

@description('Display name for the GitHub Actions app')
param displayName string = 'GitHub Actions Deploy'

@description('Unique name for the GitHub Actions app')
param appName string = 'github-actions-deploy'

// Constants
var githubOIDCProvider = 'https://token.actions.githubusercontent.com'
var microsoftEntraAudience = 'api://AzureADTokenExchange'

// Create app registration for GitHub Actions
resource githubApp 'Microsoft.Graph/applications@v1.0' = {
  displayName: displayName
  uniqueName: appName

  // Create federated identity credential for main branch
  resource mainBranchFIC 'federatedIdentityCredentials@v1.0' = {
    name: '${githubApp.uniqueName}/github-main-branch'
    audiences: [
      microsoftEntraAudience
    ]
    issuer: githubOIDCProvider
    subject: 'repo:${gitHubOwner}/${gitHubRepo}:ref:refs/heads/${gitHubBranch}'
    description: 'GitHub Actions for ${gitHubBranch} branch'
  }

  // Create federated identity credential for pull requests
  resource prFIC 'federatedIdentityCredentials@v1.0' = {
    name: '${githubApp.uniqueName}/github-pull-request'
    audiences: [
      microsoftEntraAudience
    ]
    issuer: githubOIDCProvider
    subject: 'repo:${gitHubOwner}/${gitHubRepo}:pull_request'
    description: 'GitHub Actions for pull requests'
  }

  // Create federated identity credential for environments
  resource envFIC 'federatedIdentityCredentials@v1.0' = {
    name: '${githubApp.uniqueName}/github-environment'
    audiences: [
      microsoftEntraAudience
    ]
    issuer: githubOIDCProvider
    subject: 'repo:${gitHubOwner}/${gitHubRepo}:environment:production'
    description: 'GitHub Actions for production environment'
  }
}

// Create service principal for the GitHub app
resource githubSp 'Microsoft.Graph/servicePrincipals@v1.0' = {
  appId: githubApp.appId
  displayName: displayName
}

// Assign contributor role to the service principal
resource contributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, 'github-actions-contributor')
  scope: resourceGroup()
  properties: {
    principalId: githubSp.id
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b24988ac-6180-42a0-ab88-20f7382dd24c') // Contributor
    principalType: 'ServicePrincipal'
  }
}

output appId string = githubApp.appId
output servicePrincipalId string = githubSp.id
output displayName string = githubApp.displayName
