#!/bin/bash

# Script to download and analyze Azure App Service deployment logs

# Check if required parameters are provided
if [ $# -lt 2 ]; then
    echo "Usage: $0 <app-name> <resource-group>"
    exit 1
fi

APP_NAME=$1
RESOURCE_GROUP=$2
OUTPUT_DIR="deployment-logs-$(date +%Y%m%d-%H%M%S)"

echo "Downloading deployment logs for $APP_NAME..."
mkdir -p "$OUTPUT_DIR"

# Download all logs
echo "1. Downloading deployment logs..."
az webapp log download \
    --name "$APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --log-file "$OUTPUT_DIR/logs.zip" \
    2>&1 | tee "$OUTPUT_DIR/download.log"

# Extract logs
echo "2. Extracting logs..."
cd "$OUTPUT_DIR"
python3 -m zipfile -e logs.zip . 2>/dev/null || echo "Could not extract logs.zip"

# Look for Oryx build logs
echo "3. Looking for Oryx build logs..."
find . -name "*oryx*" -type f | while read -r file; do
    echo "Found: $file"
    echo "Content:"
    cat "$file"
    echo "---"
done

# Look for deployment logs
echo "4. Looking for deployment logs..."
find . -path "*/deployments/*" -name "*.log" | while read -r file; do
    echo "Found: $file"
    echo "First 100 lines:"
    head -100 "$file"
    echo "---"
done

# Look for specific error patterns
echo "5. Searching for error patterns..."
grep -r -i "error\|fail\|exception\|traceback" . | grep -v ".zip" | head -50

# Check recent deployment status
echo "6. Recent deployment status:"
az webapp deployment source show \
    --name "$APP_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --output json 2>/dev/null || echo "Could not get deployment status"

echo "Logs saved to: $OUTPUT_DIR"
