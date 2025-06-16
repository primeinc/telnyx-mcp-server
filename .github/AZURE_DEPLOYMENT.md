# Azure Deployment Workflow Configuration

This document explains the Azure deployment workflow setup that prevents double deployments and adds environment protection.

## Problem Solved

**Issue**: The workflow was triggering deployments on both `push` and `pull_request` events for the same branch, causing double deployments.

**Solution**: 
- ✅ Limited deployment to only `pull_request` events targeting the `main` branch
- ✅ Added environment protection with required reviewers for manual validation
- ✅ Only deploys when a PR is actually merged (not just opened or synchronized)

## Workflow Configuration

The workflow is configured in `.github/workflows/azure-deploy.yml` with:

### Trigger Configuration
```yaml
"on":
  pull_request:
    branches: [main]
    types: [opened, synchronize, closed]
```

### Environment Protection
```yaml
environment: production
```

### Conditional Deployment
```yaml
if: github.event.pull_request.merged == true
```

## Repository Setup Required

To complete the configuration, repository administrators need to set up the `production` environment:

1. **Go to Repository Settings**
   - Navigate to Settings → Environments

2. **Create Production Environment**
   - Click "New environment"
   - Name: `production`

3. **Configure Required Reviewers**
   - Add required reviewers under "Protection rules"
   - Select team members who should approve deployments
   - Optionally add deployment restrictions (branches, tags)

4. **Additional Protection Rules** (Optional)
   - Deployment branches: Restrict to specific branches
   - Wait timer: Add delay before deployment starts
   - Required secrets: Environment-specific secrets

## How It Works

1. **PR Created/Updated**: Workflow runs but waits due to conditional
2. **PR Merged**: Deployment job starts and waits for environment approval
3. **Manual Approval**: Required reviewers approve the deployment
4. **Deployment Proceeds**: Azure deployment executes after approval

## Benefits

- **No Double Deployments**: Only triggers on PR merge, not on every push
- **Manual Validation**: Requires explicit approval before deployment
- **Audit Trail**: All deployments tracked with reviewer information
- **Security**: Prevents unauthorized deployments to production

## Testing

Run the validation test:
```bash
python /tmp/test_azure_workflow.py
```

This ensures the workflow configuration meets all requirements.