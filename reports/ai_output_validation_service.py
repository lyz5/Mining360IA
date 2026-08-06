from __future__ import annotations

from .ai_provider_types import AIProviderError


class AIOutputValidationService:
    def validate(self, value, schema: dict | None):
        if not schema:
            return value
        errors = []
        self._validate(value, schema, "$", errors)
        if errors:
            raise AIProviderError(
                "INVALID_STRUCTURED_OUTPUT",
                "; ".join(errors[:8]),
                status_code=502,
                retryable=False,
            )
        return value

    def _validate(self, value, schema, path, errors):
        expected = schema.get("type")
        type_map = {
            "object": dict,
            "array": list,
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "null": type(None),
        }
        if expected in type_map and not isinstance(value, type_map[expected]):
            errors.append(f"{path} must be {expected}")
            return
        if "enum" in schema and value not in schema["enum"]:
            errors.append(f"{path} is not an allowed value")
        if expected == "object":
            for key in schema.get("required", []):
                if key not in value:
                    errors.append(f"{path}.{key} is required")
            properties = schema.get("properties", {})
            for key, item in value.items():
                if key in properties:
                    self._validate(item, properties[key], f"{path}.{key}", errors)
                elif schema.get("additionalProperties") is False:
                    errors.append(f"{path}.{key} is not allowed")
        elif expected == "array" and schema.get("items"):
            for index, item in enumerate(value):
                self._validate(item, schema["items"], f"{path}[{index}]", errors)


output_validation_service = AIOutputValidationService()
