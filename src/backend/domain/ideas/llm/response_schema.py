from typing import Any

from pydantic import BaseModel


def build_response_schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})

    def simplify(node: dict[str, Any]) -> dict[str, Any]:
        reference = node.get("$ref")
        if reference is not None:
            prefix = "#/$defs/"
            if not reference.startswith(prefix):
                raise ValueError(f"Unsupported response schema reference: {reference}")
            return simplify(definitions[reference.removeprefix(prefix)])

        if "anyOf" in node:
            options = node["anyOf"]
            nullable = any(option.get("type") == "null" for option in options)
            value_options = [
                option for option in options if option.get("type") != "null"
            ]
            if len(value_options) == 1:
                result = simplify(value_options[0])
                if nullable:
                    result["nullable"] = True
                return result
            if value_options and all(
                option.get("type") in {"integer", "number", "string"}
                for option in value_options
            ):
                result = {"type": "string"}
                if nullable:
                    result["nullable"] = True
                return result
            raise ValueError("Unsupported union in Gemini response schema")

        result: dict[str, Any] = {}
        if "type" in node:
            result["type"] = node["type"]
        if "properties" in node:
            result["properties"] = {
                name: simplify(property_schema)
                for name, property_schema in node["properties"].items()
            }
        if "required" in node:
            result["required"] = node["required"]
        if "items" in node:
            result["items"] = simplify(node["items"])
        if "enum" in node:
            result["enum"] = node["enum"]
        if "const" in node:
            result["enum"] = [node["const"]]
        if isinstance(node.get("additionalProperties"), dict):
            result["additionalProperties"] = simplify(node["additionalProperties"])
        elif "additionalProperties" in node:
            result["additionalProperties"] = node["additionalProperties"]
        return result

    return simplify(schema)
