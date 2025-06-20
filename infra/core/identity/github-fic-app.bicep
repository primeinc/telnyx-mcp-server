extension microsoftGraphV1

targetScope = 'tenant'

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

  // Create federated identity credential for production environment
  resource prodEnvFIC 'federatedIdentityCredentials@v1.0' = {
    name: '${githubApp.uniqueName}/github-environment-production'
    audiences: [
      microsoftEntraAudience
    ]
    issuer: githubOIDCProvider
    subject: 'repo:${gitHubOwner}/${gitHubRepo}:environment:production'
    description: 'GitHub Actions for production environment'
  }

  // Create federated identity credential for staging environment
  resource stagingEnvFIC 'federatedIdentityCredentials@v1.0' = {
    name: '${githubApp.uniqueName}/github-environment-staging'
    audiences: [
      microsoftEntraAudience
    ]
    issuer: githubOIDCProvider
    subject: 'repo:${gitHubOwner}/${gitHubRepo}:environment:staging'
    description: 'GitHub Actions for staging environment'
  }

  // Create federated identity credential for development environment
  resource devEnvFIC 'federatedIdentityCredentials@v1.0' = {
    name: '${githubApp.uniqueName}/github-environment-development'
    audiences: [
      microsoftEntraAudience
    ]
    issuer: githubOIDCProvider
    subject: 'repo:${gitHubOwner}/${gitHubRepo}:environment:development'
    description: 'GitHub Actions for development environment'
  }
}

// Create service principal for the GitHub app
resource githubSp 'Microsoft.Graph/servicePrincipals@v1.0' = {
  appId: githubApp.appId
  displayName: displayName
}

output appId string = githubApp.appId
output servicePrincipalId string = githubSp.id
output displayName string = githubApp.displayName
