# Check Azure App Service Deployment

This command checks the deployment status and logs for the Telnyx MCP Server on Azure App Service.

## Usage
```
/check-deployment
```

## What it does:
1. Shows recent deployment history
2. Gets detailed deployment logs
3. Extracts the Oryx build output URL
4. Attempts to fetch the detailed build log

## Azure Resources:
- Resource Group: `rg-telnyxmcp-dev-001`
- App Service: `app-telnyxmcp-dev-eus2-001`

## Commands executed:
```bash
# Get deployment logs
az webapp log deployment show -g rg-telnyxmcp-dev-001 -n app-telnyxmcp-dev-eus2-001 --output json

# Extract the Oryx build details URL from the logs
# Look for entries with type: 2 and a details_url

# Attempt to fetch the detailed build log (requires auth)
curl -s "https://app-telnyxmcp-dev-eus2-001.scm.azurewebsites.net/api/deployments/{deployment-id}/log/{log-id}"
```

## Common issues to look for:
- Syntax errors in appsvc.yaml (watch for double semicolons `;;`)
- Missing requirements.txt
- Failed pip installations
- Module import errors during build

## Alternative if curl fails:
Use Kudu console at https://app-telnyxmcp-dev-eus2-001.scm.azurewebsites.net to view logs directly.
