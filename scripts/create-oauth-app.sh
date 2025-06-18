#!/bin/bash
# Script to create OAuth app registration for Telnyx MCP Server

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
print_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check if user is logged in to Azure
if ! az account show &>/dev/null; then
    print_error "Not logged in to Azure. Please run 'az login' first."
    exit 1
fi

# Get current tenant info
TENANT_ID=$(az account show --query tenantId -o tsv)
print_info "Using tenant: $TENANT_ID"

# Generate app name with timestamp to ensure uniqueness
APP_NAME="telnyx-mcp-server-oauth-$(date +%Y%m%d%H%M%S)"
print_info "Creating OAuth app registration: $APP_NAME"

# Create the app registration
APP_INFO=$(az ad app create \
    --display-name "$APP_NAME" \
    --sign-in-audience "AzureADMyOrg" \
    --enable-access-token-issuance false \
    --enable-id-token-issuance true \
    --web-redirect-uris "http://localhost:8000/auth/callback" \
    --query "{appId:appId, id:id}"
)

# Extract app ID
APP_ID=$(echo "$APP_INFO" | jq -r '.appId')
OBJECT_ID=$(echo "$APP_INFO" | jq -r '.id')

print_info "Created app with ID: $APP_ID"

# Create a client secret
print_info "Creating client secret..."
SECRET_INFO=$(az ad app credential reset \
    --id "$APP_ID" \
    --display-name "azd-deployment" \
    --years 2)

CLIENT_SECRET=$(echo "$SECRET_INFO" | jq -r '.password')

# Create service principal for the app
print_info "Creating service principal..."
SP_INFO=$(az ad sp create --id "$APP_ID")
SP_ID=$(echo "$SP_INFO" | jq -r '.id')
print_info "Created service principal with ID: $SP_ID"

# Add Microsoft Graph API permissions
print_info "Adding Microsoft Graph permissions..."

# User.Read - Sign in and read user profile
az ad app permission add --id "$APP_ID" \
    --api 00000003-0000-0000-c000-000000000000 \
    --api-permissions e1fe6dd8-ba31-4d61-89e7-88639da4683d=Scope 2>/dev/null

# openid - Sign users in
az ad app permission add --id "$APP_ID" \
    --api 00000003-0000-0000-c000-000000000000 \
    --api-permissions 37f7f235-527c-4136-accd-4a02d197296e=Scope 2>/dev/null

# profile - View users' basic profile
az ad app permission add --id "$APP_ID" \
    --api 00000003-0000-0000-c000-000000000000 \
    --api-permissions 14dad69e-099b-42c9-810b-d002981feec1=Scope 2>/dev/null

print_info "Permissions added"

# Wait for propagation
print_info "Waiting for changes to propagate..."
sleep 5

# Grant the permissions to make them effective
print_info "Granting permissions to service principal..."
az ad app permission grant --id "$APP_ID" \
    --api 00000003-0000-0000-c000-000000000000 \
    --scope "User.Read openid profile" >/dev/null

# Grant admin consent for the required permissions
print_info "Granting admin consent for Microsoft Graph permissions..."
if az ad app permission admin-consent --id "$APP_ID"; then
    print_info "Admin consent granted successfully!"
else
    print_warn "Admin consent failed. You may need to grant consent manually in the Azure Portal"
    print_warn "The app has been created successfully and can be used after consent is granted"
fi

# Output the configuration
print_info "OAuth app registration created successfully!"
echo ""
echo "========================================"
echo "OAUTH APP REGISTRATION DETAILS"
echo "========================================"
echo "App Name: $APP_NAME"
echo "App ID (Client ID): $APP_ID"
echo "Object ID: $OBJECT_ID"
echo "Tenant ID: $TENANT_ID"
echo ""
echo "========================================"
echo "NEXT STEPS:"
echo "========================================"
echo "1. Set these values in your azd environment:"
echo ""
echo "   azd env set AZURE_OAUTH_CLIENT_ID \"$APP_ID\""
echo "   azd env set AZURE_OAUTH_CLIENT_SECRET \"$CLIENT_SECRET\""
echo ""
echo "2. After running 'azd up', run the post-deployment script:"
echo "   ./scripts/setup-oauth-redirect.sh"
echo ""
echo "3. Save the client secret securely - it cannot be retrieved again!"
echo ""
print_warn "Initial redirect URI set to: http://localhost:8000/auth/callback"
print_warn "Additional redirect URIs will be added automatically after deployment"
