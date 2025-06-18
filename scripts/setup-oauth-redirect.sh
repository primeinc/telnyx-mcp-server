#!/bin/bash
# Post-deployment script to add redirect URI to OAuth app registration

set -e

echo "Setting up OAuth redirect URI..."

# Get environment values from azd
WEB_URI=$(azd env get-value WEB_URI 2>/dev/null || echo "")
OAUTH_APP_ID=$(azd env get-value AZURE_OAUTH_CLIENT_ID 2>/dev/null || echo "")

if [ -z "$WEB_URI" ]; then
    echo "Error: WEB_URI not found. Make sure you've run 'azd up' first."
    exit 1
fi

if [ -z "$OAUTH_APP_ID" ]; then
    echo "Error: AZURE_OAUTH_CLIENT_ID not found. Please set it with:"
    echo "  azd env set AZURE_OAUTH_CLIENT_ID <your-oauth-app-id>"
    exit 1
fi

# Construct the redirect URI - ensure no trailing slash on WEB_URI
WEB_URI="${WEB_URI%/}"
REDIRECT_URI="${WEB_URI}/auth/callback"

echo "Web App URL: $WEB_URI"
echo "OAuth App ID: $OAUTH_APP_ID"
echo "Redirect URI: $REDIRECT_URI"

# Check if the redirect URI already exists
echo "Checking existing redirect URIs..."
EXISTING_URIS=$(az ad app show --id "$OAUTH_APP_ID" --query "web.redirectUris" -o json)

if echo "$EXISTING_URIS" | grep -q "$REDIRECT_URI"; then
    echo "Redirect URI already exists. No action needed."
    exit 0
fi

# Add the redirect URI
echo "Adding redirect URI to OAuth app..."
az ad app update --id "$OAUTH_APP_ID" --web-redirect-uris "$REDIRECT_URI" "http://localhost:8000/auth/callback"

echo "✅ Successfully added redirect URI to OAuth app registration"
echo ""
echo "Next steps:"
echo "1. Test the OAuth flow by visiting: $WEB_URI"
echo "2. Click 'Sign in with Azure AD' to test authentication"
