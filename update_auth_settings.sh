#\!/bin/bash

# Set the URLs with actual values
authsettingsv2_list_url="https://management.azure.com/subscriptions/98a49ff3-2204-48c2-9908-6d6c121ee372/resourceGroups/rg-telnyxmcp-staging-001/providers/Microsoft.Web/sites/app-telnyxmcp-staging-eus2-001/config/authsettingsv2/list?api-version=2020-09-01"
authsettingsv2_url="https://management.azure.com/subscriptions/98a49ff3-2204-48c2-9908-6d6c121ee372/resourceGroups/rg-telnyxmcp-staging-001/providers/Microsoft.Web/sites/app-telnyxmcp-staging-eus2-001/config/authsettingsv2?api-version=2020-09-01"

echo "1. Downloading current auth settings..."
az rest --method GET --url "$authsettingsv2_list_url" > authsettingsv2_current_live.json

echo "2. Current auth settings saved to authsettingsv2_current_live.json"
echo "3. The file has been modified to add /oauth/callback/debug to excludedPaths"
echo "4. To update the settings, run:"
echo ""
echo "az rest --method PUT --url \"$authsettingsv2_url\" --body @./authsettingsv2_current.json"
