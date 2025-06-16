"""Tool schema processing using Pydantic models for better reliability and validation."""

from typing import Dict, Any, List, Optional, Union, Type
from pydantic import BaseModel, Field, ValidationError, create_model
import logging
import inspect
import re

logger = logging.getLogger(__name__)


# Base schema models for common tool patterns
class MessageToolSchema(BaseModel):
    """Schema for message-related tools."""
    from_: str = Field(..., alias="from", description="Sending address (phone number, alphanumeric sender ID, or short code)")
    to: str = Field(..., description="Receiving address")
    text: str = Field(..., description="Message text")
    messaging_profile_id: Optional[str] = Field(None, description="Messaging profile ID")
    subject: Optional[str] = Field(None, description="Message subject")
    media_urls: Optional[List[str]] = Field(None, description="List of media URLs")
    webhook_url: Optional[str] = Field(None, description="Webhook URL")
    type: Optional[str] = Field(None, description="The protocol for sending the message")


class MessageRetrievalSchema(BaseModel):
    """Schema for retrieving a message."""
    message_id: str = Field(..., description="The ID of the message to retrieve")


class PhoneNumberListSchema(BaseModel):
    """Schema for listing phone numbers."""
    page: Optional[int] = Field(1, description="Page number")
    page_size: Optional[int] = Field(20, description="Page size")
    filter_phone_number: Optional[str] = Field(None, description="Filter by phone number")
    filter_status: Optional[str] = Field(None, description="Filter by status")
    filter_voice_enabled: Optional[bool] = Field(None, description="Filter by voice enabled")


class AssistantRetrievalSchema(BaseModel):
    """Schema for retrieving an assistant."""
    assistant_id: str = Field(..., description="Assistant ID")


class AssistantCallSchema(BaseModel):
    """Schema for starting an assistant call."""
    assistant_id: str = Field(..., description="ID of the assistant to use for the call")
    to: str = Field(..., description="Destination phone number to call")
    from_: str = Field(..., alias="from", description="Source phone number to call from (must be a number on your Telnyx account)")


class CloudStorageBucketSchema(BaseModel):
    """Schema for cloud storage bucket operations."""
    bucket_name: str = Field(..., description="Name of the bucket")
    region: Optional[str] = Field(None, description="Region to create the bucket in")


class CloudStorageFileSchema(BaseModel):
    """Schema for cloud storage file operations."""
    bucket_name: str = Field(..., description="Name of the bucket")
    file_key: str = Field(..., description="Key/path of the file in the bucket")
    local_path: Optional[str] = Field(None, description="Local path for file operations")


class IntegrationSecretCreateSchema(BaseModel):
    """Schema for creating integration secrets."""
    identifier: str = Field(..., description="The unique identifier of the secret")
    type: str = Field(..., description="The type of secret (bearer, basic)")
    token: Optional[str] = Field(None, description="The token for the secret (required for bearer type)")
    username: Optional[str] = Field(None, description="The username for the secret (required for basic type)")
    password: Optional[str] = Field(None, description="The password for the secret (required for basic type)")


class IntegrationSecretListSchema(BaseModel):
    """Schema for listing integration secrets."""
    page: Optional[int] = Field(1, description="Page number")
    page_size: Optional[int] = Field(25, description="Page size")
    filter_type: Optional[str] = Field(None, description="Filter by secret type (bearer, basic)")


class IntegrationSecretDeleteSchema(BaseModel):
    """Schema for deleting integration secrets."""
    id: str = Field(..., description="Secret ID as string")


# Mapping of tool names to their Pydantic schemas
TOOL_SCHEMAS: Dict[str, Type[BaseModel]] = {
    "send_message": MessageToolSchema,
    "get_message": MessageRetrievalSchema,
    "list_phone_numbers": PhoneNumberListSchema,
    "get_assistant": AssistantRetrievalSchema,
    "start_assistant_call": AssistantCallSchema,
    "cloud_storage_create_bucket": CloudStorageBucketSchema,
    "cloud_storage_upload_file": CloudStorageFileSchema,
    "cloud_storage_download_file": CloudStorageFileSchema,
    "cloud_storage_delete_object": CloudStorageFileSchema,
    "cloud_storage_get_bucket_location": CloudStorageBucketSchema,
    "create_integration_secret": IntegrationSecretCreateSchema,
    "list_integration_secrets": IntegrationSecretListSchema,
    "delete_integration_secret": IntegrationSecretDeleteSchema,
}


def extract_docstring_parameters(docstring: str) -> Dict[str, Any]:
    """Extract parameter definitions from docstring as fallback.
    
    This provides backward compatibility for tools not yet using Pydantic schemas.
    
    Args:
        docstring: The function docstring
        
    Returns:
        JSON schema dictionary with extracted parameters
    """
    if not docstring:
        return {"type": "object", "properties": {}, "required": []}
    
    lines = docstring.split('\n')
    in_args = False
    properties = {}
    required = []
    
    for line in lines:
        line = line.strip()
        
        # Start of Args section
        if line.startswith("Args:"):
            in_args = True
            continue
        
        # End of Args section
        if in_args and (line.startswith("Returns:") or line.startswith("Raises:") or (line == "" and not lines)):
            break
        
        # Parse parameter lines
        if in_args and line and ":" in line:
            parts = line.split(":", 1)
            param_name = parts[0].strip()
            description = parts[1].strip() if len(parts) > 1 else ""
            
            # Extract type and required status from description
            is_required = "Required." in description or "required." in description
            is_optional = "Optional" in description or "optional" in description
            
            # Determine type from description
            param_type = "string"  # default
            if "boolean" in description.lower() or "bool" in description.lower():
                param_type = "boolean"
            elif "integer" in description.lower() or "int" in description.lower():
                param_type = "integer"
            elif "number" in description.lower() or "float" in description.lower():
                param_type = "number"
            elif "array" in description.lower() or "list" in description.lower():
                param_type = "array"
            elif "object" in description.lower() or "dict" in description.lower():
                param_type = "object"
            
            # Clean up parameter name (remove trailing underscore)
            clean_name = param_name.rstrip('_')
            
            properties[clean_name] = {
                "type": param_type,
                "description": description
            }
            
            if is_required and not is_optional:
                required.append(clean_name)
    
    return {
        "type": "object",
        "properties": properties,
        "required": required
    }


def pydantic_to_json_schema(model: Type[BaseModel]) -> Dict[str, Any]:
    """Convert a Pydantic model to JSON schema.
    
    Args:
        model: The Pydantic model class
        
    Returns:
        JSON schema dictionary
    """
    try:
        # Get the JSON schema from the Pydantic model
        schema = model.model_json_schema()
        
        # Extract the main properties and required fields
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        
        # Clean up the schema for MCP compatibility
        cleaned_properties = {}
        for prop_name, prop_def in properties.items():
            # Handle field aliases (like from_ -> from)
            if "from_" in prop_name:
                cleaned_properties["from"] = prop_def
            else:
                cleaned_properties[prop_name] = prop_def
            
            # Remove Pydantic-specific fields
            prop_def.pop("title", None)
            prop_def.pop("default", None)
        
        return {
            "type": "object",
            "properties": cleaned_properties,
            "required": required
        }
        
    except Exception as e:
        logger.error(f"Failed to convert Pydantic model to JSON schema: {e}")
        return {"type": "object", "properties": {}, "required": []}


def validate_tool_arguments(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Validate tool arguments against the schema and return cleaned arguments.
    
    Args:
        tool_name: Name of the tool
        arguments: Arguments to validate
        
    Returns:
        Validated and cleaned arguments
        
    Raises:
        ValidationError: If arguments don't match the schema
    """
    schema_model = TOOL_SCHEMAS.get(tool_name)
    
    if not schema_model:
        # No specific schema, return arguments as-is
        return arguments
    
    try:
        # Handle field aliases (from -> from_)
        if "from" in arguments and tool_name in ["send_message", "start_assistant_call"]:
            arguments["from_"] = arguments.pop("from")
        
        # Validate using Pydantic
        validated = schema_model.model_validate(arguments)
        
        # Convert back to dict and handle aliases
        result = validated.model_dump(by_alias=True)
        
        return result
        
    except ValidationError as e:
        logger.error(f"Validation error for tool {tool_name}: {e}")
        raise


def fix_tool_schema(tool: Dict[str, Any]) -> Dict[str, Any]:
    """Fix tool schema by using Pydantic models or fallback to docstring parsing.
    
    Args:
        tool: Tool definition with name, description, and inputSchema
        
    Returns:
        Tool definition with corrected schema
    """
    tool_name = tool.get("name", "")
    
    # Check if we have a Pydantic schema for this tool
    if tool_name in TOOL_SCHEMAS:
        schema_model = TOOL_SCHEMAS[tool_name]
        try:
            json_schema = pydantic_to_json_schema(schema_model)
            
            # Create updated tool definition
            updated_tool = tool.copy()
            updated_tool["inputSchema"] = json_schema
            
            logger.debug(f"Applied Pydantic schema for tool: {tool_name}")
            return updated_tool
            
        except Exception as e:
            logger.warning(f"Failed to apply Pydantic schema for {tool_name}: {e}")
    
    # Check if tool has nested request pattern that needs flattening
    input_schema = tool.get("inputSchema", {})
    properties = input_schema.get("properties", {})
    
    if len(properties) == 1 and "request" in properties:
        # This tool has a nested request object - extract from docstring
        docstring = tool.get("description", "")
        flattened_schema = extract_docstring_parameters(docstring)
        
        if flattened_schema.get("properties"):
            updated_tool = tool.copy()
            updated_tool["inputSchema"] = flattened_schema
            logger.debug(f"Flattened schema from docstring for tool: {tool_name}")
            return updated_tool
    
    # Return original tool if no changes needed
    return tool


def validate_schema_model(model: Type[BaseModel]) -> List[str]:
    """Validate a Pydantic schema model for common issues.
    
    Args:
        model: The Pydantic model to validate
        
    Returns:
        List of validation errors/warnings
    """
    errors = []
    
    try:
        # Check if model can generate JSON schema
        schema = model.model_json_schema()
        
        # Validate required fields are present
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        
        for req_field in required:
            if req_field not in properties:
                errors.append(f"Required field '{req_field}' not found in properties")
        
        # Check for proper descriptions
        for prop_name, prop_def in properties.items():
            if not prop_def.get("description"):
                errors.append(f"Property '{prop_name}' missing description")
        
        # Try to create an instance with minimal data
        test_data = {}
        for req_field in required:
            prop_def = properties.get(req_field, {})
            prop_type = prop_def.get("type", "string")
            
            if prop_type == "string":
                test_data[req_field] = "test"
            elif prop_type == "integer":
                test_data[req_field] = 1
            elif prop_type == "boolean":
                test_data[req_field] = True
            elif prop_type == "array":
                test_data[req_field] = []
            elif prop_type == "object":
                test_data[req_field] = {}
        
        # Test validation
        model.model_validate(test_data)
        
    except Exception as e:
        errors.append(f"Schema model validation failed: {e}")
    
    return errors


def register_tool_schema(tool_name: str, schema_model: Type[BaseModel]) -> None:
    """Register a new tool schema.
    
    Args:
        tool_name: Name of the tool
        schema_model: Pydantic model class for the schema
    """
    # Validate the schema first
    errors = validate_schema_model(schema_model)
    if errors:
        logger.warning(f"Schema validation warnings for {tool_name}: {errors}")
    
    TOOL_SCHEMAS[tool_name] = schema_model
    logger.info(f"Registered schema for tool: {tool_name}")


def get_tool_schema_info() -> Dict[str, Any]:
    """Get information about registered tool schemas.
    
    Returns:
        Dictionary with schema information
    """
    return {
        "total_schemas": len(TOOL_SCHEMAS),
        "tools_with_schemas": list(TOOL_SCHEMAS.keys()),
        "schema_coverage": f"{len(TOOL_SCHEMAS)} tools with Pydantic schemas"
    }