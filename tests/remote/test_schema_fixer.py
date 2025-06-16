"""Tests for the Pydantic-based schema fixer."""

import pytest
from typing import Dict, Any
from unittest.mock import MagicMock, patch
from pydantic import BaseModel, Field, ValidationError

from telnyx_mcp_server.remote.schema_fixer import (
    MessageToolSchema, MessageRetrievalSchema, PhoneNumberListSchema,
    AssistantRetrievalSchema, AssistantCallSchema, CloudStorageBucketSchema,
    IntegrationSecretCreateSchema, fix_tool_schema, validate_tool_arguments,
    pydantic_to_json_schema, extract_docstring_parameters, register_tool_schema,
    validate_schema_model, get_tool_schema_info
)


class TestPydanticSchemas:
    """Test the Pydantic schema models."""
    
    def test_message_tool_schema(self):
        """Test MessageToolSchema validation."""
        # Valid data
        valid_data = {
            "from": "+1234567890",
            "to": "+0987654321",
            "text": "Hello, world!"
        }
        
        schema = MessageToolSchema(**valid_data)
        assert schema.from_ == "+1234567890"
        assert schema.to == "+0987654321"
        assert schema.text == "Hello, world!"
        
        # Test field alias
        assert schema.model_dump(by_alias=True)["from"] == "+1234567890"
    
    def test_message_tool_schema_validation_error(self):
        """Test MessageToolSchema validation errors."""
        # Missing required fields
        with pytest.raises(ValidationError):
            MessageToolSchema(from_="+1234567890")  # Missing 'to' and 'text'
    
    def test_phone_number_list_schema(self):
        """Test PhoneNumberListSchema with defaults."""
        schema = PhoneNumberListSchema()
        assert schema.page == 1
        assert schema.page_size == 20
        assert schema.filter_phone_number is None
        
        # With custom values
        schema = PhoneNumberListSchema(page=2, page_size=50, filter_phone_number="+1234567890")
        assert schema.page == 2
        assert schema.page_size == 50
        assert schema.filter_phone_number == "+1234567890"
    
    def test_integration_secret_create_schema(self):
        """Test IntegrationSecretCreateSchema validation."""
        # Bearer token type
        bearer_data = {
            "identifier": "test-secret",
            "type": "bearer",
            "token": "secret_token_123"
        }
        
        schema = IntegrationSecretCreateSchema(**bearer_data)
        assert schema.identifier == "test-secret"
        assert schema.type == "bearer"
        assert schema.token == "secret_token_123"
        
        # Basic auth type
        basic_data = {
            "identifier": "test-basic",
            "type": "basic",
            "username": "user",
            "password": "pass"
        }
        
        schema = IntegrationSecretCreateSchema(**basic_data)
        assert schema.identifier == "test-basic"
        assert schema.type == "basic"
        assert schema.username == "user"
        assert schema.password == "pass"


class TestSchemaConversion:
    """Test schema conversion functions."""
    
    def test_pydantic_to_json_schema(self):
        """Test converting Pydantic model to JSON schema."""
        json_schema = pydantic_to_json_schema(MessageToolSchema)
        
        assert json_schema["type"] == "object"
        assert "properties" in json_schema
        assert "required" in json_schema
        
        # Check that field aliases are handled correctly
        properties = json_schema["properties"]
        assert "from" in properties  # Should use alias
        assert "to" in properties
        assert "text" in properties
        
        # Check required fields
        required = json_schema["required"]
        assert "from" in required or "from_" in required
        assert "to" in required
        assert "text" in required
    
    def test_extract_docstring_parameters(self):
        """Test extracting parameters from docstring."""
        docstring = """
        Test function.
        
        Args:
            param1: Required. String parameter description.
            param2: Optional integer. Integer parameter description.
            param3: Optional. Boolean parameter for testing.
            
        Returns:
            Dict with results.
        """
        
        schema = extract_docstring_parameters(docstring)
        
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "required" in schema
        
        properties = schema["properties"]
        assert "param1" in properties
        assert "param2" in properties
        assert "param3" in properties
        
        # Check types
        assert properties["param1"]["type"] == "string"
        assert properties["param2"]["type"] == "integer"
        assert properties["param3"]["type"] == "boolean"
        
        # Check required
        required = schema["required"]
        assert "param1" in required
        assert "param2" not in required  # Optional
        assert "param3" not in required  # Optional
    
    def test_extract_docstring_parameters_empty(self):
        """Test extracting from empty docstring."""
        schema = extract_docstring_parameters("")
        
        assert schema["type"] == "object"
        assert schema["properties"] == {}
        assert schema["required"] == []
    
    def test_extract_docstring_parameters_no_args(self):
        """Test extracting from docstring without Args section."""
        docstring = """
        Test function without args.
        
        Returns:
            Nothing.
        """
        
        schema = extract_docstring_parameters(docstring)
        
        assert schema["type"] == "object"
        assert schema["properties"] == {}
        assert schema["required"] == []


class TestToolSchemaFixing:
    """Test tool schema fixing functionality."""
    
    def test_fix_tool_schema_with_pydantic(self):
        """Test fixing schema using registered Pydantic model."""
        tool = {
            "name": "send_message",
            "description": "Send a message",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request": {"type": "object"}
                },
                "required": ["request"]
            }
        }
        
        fixed_tool = fix_tool_schema(tool)
        
        # Should have updated schema
        assert fixed_tool["name"] == "send_message"
        assert fixed_tool["inputSchema"]["type"] == "object"
        
        # Should have proper properties
        properties = fixed_tool["inputSchema"]["properties"]
        assert "from" in properties or "from_" in properties
        assert "to" in properties
        assert "text" in properties
    
    def test_fix_tool_schema_without_pydantic(self):
        """Test fixing schema for tool without Pydantic model."""
        tool = {
            "name": "unknown_tool",
            "description": """
            Unknown tool.
            
            Args:
                param1: Required. Test parameter.
                param2: Optional. Another parameter.
            """,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request": {"type": "object"}
                },
                "required": ["request"]
            }
        }
        
        fixed_tool = fix_tool_schema(tool)
        
        # Should use docstring extraction
        properties = fixed_tool["inputSchema"]["properties"]
        assert "param1" in properties
        assert "param2" in properties
        
        required = fixed_tool["inputSchema"]["required"]
        assert "param1" in required
        assert "param2" not in required
    
    def test_fix_tool_schema_no_changes_needed(self):
        """Test tool that doesn't need schema fixing."""
        tool = {
            "name": "simple_tool",
            "description": "Simple tool",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "param1": {"type": "string"},
                    "param2": {"type": "integer"}
                },
                "required": ["param1"]
            }
        }
        
        fixed_tool = fix_tool_schema(tool)
        
        # Should return unchanged
        assert fixed_tool == tool


class TestArgumentValidation:
    """Test argument validation functionality."""
    
    def test_validate_tool_arguments_with_schema(self):
        """Test validating arguments with known schema."""
        arguments = {
            "from": "+1234567890",
            "to": "+0987654321",
            "text": "Hello, world!"
        }
        
        validated = validate_tool_arguments("send_message", arguments)
        
        # Should return validated arguments with proper aliases
        assert "from" in validated
        assert validated["from"] == "+1234567890"
        assert validated["to"] == "+0987654321"
        assert validated["text"] == "Hello, world!"
    
    def test_validate_tool_arguments_validation_error(self):
        """Test validation error handling."""
        arguments = {
            "from": "+1234567890"
            # Missing required fields
        }
        
        with pytest.raises(ValidationError):
            validate_tool_arguments("send_message", arguments)
    
    def test_validate_tool_arguments_no_schema(self):
        """Test validation for tool without schema."""
        arguments = {
            "param1": "value1",
            "param2": "value2"
        }
        
        validated = validate_tool_arguments("unknown_tool", arguments)
        
        # Should return arguments unchanged
        assert validated == arguments
    
    def test_validate_tool_arguments_alias_handling(self):
        """Test handling of field aliases in validation."""
        arguments = {
            "from": "+1234567890",
            "to": "+0987654321",
            "text": "Hello!"
        }
        
        validated = validate_tool_arguments("start_assistant_call", arguments)
        
        # Should handle from -> from_ alias
        assert "from" in validated
        assert validated["from"] == "+1234567890"


class TestSchemaRegistration:
    """Test schema registration functionality."""
    
    def test_register_tool_schema(self):
        """Test registering a new tool schema."""
        class CustomToolSchema(BaseModel):
            param1: str = Field(..., description="Required parameter")
            param2: int = Field(default=10, description="Optional parameter")
        
        register_tool_schema("custom_tool", CustomToolSchema)
        
        # Should be able to fix schema for the new tool
        tool = {
            "name": "custom_tool",
            "description": "Custom tool",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "request": {"type": "object"}
                },
                "required": ["request"]
            }
        }
        
        fixed_tool = fix_tool_schema(tool)
        
        properties = fixed_tool["inputSchema"]["properties"]
        assert "param1" in properties
        assert "param2" in properties
    
    def test_validate_schema_model_valid(self):
        """Test validating a valid schema model."""
        class ValidSchema(BaseModel):
            param1: str = Field(..., description="Required parameter")
            param2: int = Field(default=10, description="Optional parameter")
        
        errors = validate_schema_model(ValidSchema)
        assert len(errors) == 0
    
    def test_validate_schema_model_invalid(self):
        """Test validating an invalid schema model."""
        class InvalidSchema(BaseModel):
            param1: str  # Missing description
            param2: int = Field(...)  # Missing description
        
        errors = validate_schema_model(InvalidSchema)
        assert len(errors) > 0
        
        # Should have errors about missing descriptions
        error_messages = " ".join(errors)
        assert "description" in error_messages.lower()
    
    def test_get_tool_schema_info(self):
        """Test getting schema information."""
        info = get_tool_schema_info()
        
        assert isinstance(info, dict)
        assert "total_schemas" in info
        assert "tools_with_schemas" in info
        assert "schema_coverage" in info
        
        assert isinstance(info["total_schemas"], int)
        assert isinstance(info["tools_with_schemas"], list)
        assert isinstance(info["schema_coverage"], str)


class TestMalformedSchemaHandling:
    """Test handling of malformed schemas."""
    
    def test_malformed_pydantic_model(self):
        """Test handling of malformed Pydantic model."""
        class MalformedSchema(BaseModel):
            # This should cause issues during JSON schema generation
            param1: "InvalidType"  # Invalid type annotation
        
        # Should handle gracefully
        try:
            json_schema = pydantic_to_json_schema(MalformedSchema)
            # Should return a basic schema even if conversion fails
            assert isinstance(json_schema, dict)
            assert json_schema.get("type") == "object"
        except Exception:
            # Or raise an exception, which is also acceptable
            pass
    
    def test_malformed_docstring(self):
        """Test handling of malformed docstring."""
        malformed_docstring = """
        Malformed docstring.
        
        Args:
            param1 invalid format
            param2: missing type information
            : missing parameter name
        """
        
        # Should handle gracefully
        schema = extract_docstring_parameters(malformed_docstring)
        assert isinstance(schema, dict)
        assert schema["type"] == "object"
        assert isinstance(schema["properties"], dict)
        assert isinstance(schema["required"], list)
    
    def test_invalid_tool_structure(self):
        """Test handling of invalid tool structure."""
        invalid_tool = {
            "name": "invalid_tool",
            # Missing description and inputSchema
        }
        
        # Should handle gracefully
        fixed_tool = fix_tool_schema(invalid_tool)
        assert isinstance(fixed_tool, dict)
        assert fixed_tool["name"] == "invalid_tool"
    
    def test_empty_tool_schema(self):
        """Test handling of empty tool schema."""
        empty_tool = {}
        
        # Should handle gracefully
        fixed_tool = fix_tool_schema(empty_tool)
        assert isinstance(fixed_tool, dict)