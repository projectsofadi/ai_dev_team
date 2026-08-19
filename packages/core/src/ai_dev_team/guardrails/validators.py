"""Input and output validation guardrails."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationResult:
    valid: bool = True
    violations: list[str] = field(default_factory=list)

    def add_violation(self, message: str) -> None:
        self.valid = False
        self.violations.append(message)


# Patterns that may indicate prompt injection attempts
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"disregard\s+(all\s+)?previous",
    r"you\s+are\s+now\s+(?:a|an)\s+",
    r"system\s*:\s*",
    r"<\|system\|>",
    r"\[INST\]",
    r"<\|im_start\|>",
]

# Patterns for detecting secrets in output
SECRET_PATTERNS = [
    (r"sk-[a-zA-Z0-9]{20,}", "OpenAI API key"),
    (r"sk-ant-[a-zA-Z0-9-]{20,}", "Anthropic API key"),
    (r"ghp_[a-zA-Z0-9]{36,}", "GitHub personal access token"),
    (r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----", "Private key"),
    (r"AKIA[0-9A-Z]{16}", "AWS access key"),
    (r"password\s*[:=]\s*['\"][^'\"]{8,}", "Hardcoded password"),
]


def validate_input(text: str) -> ValidationResult:
    """Check input for potential prompt injection patterns."""
    result = ValidationResult()

    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            result.add_violation(f"Potential prompt injection detected: matches '{pattern}'")

    if len(text) > 500_000:
        result.add_violation(f"Input too long: {len(text)} chars (max 500,000)")

    return result


def validate_output(text: str) -> ValidationResult:
    """Check output for leaked secrets or PII."""
    result = ValidationResult()

    for pattern, label in SECRET_PATTERNS:
        if re.search(pattern, text):
            result.add_violation(f"Potential {label} detected in output")

    return result


def validate_tool_args(
    args: dict[str, Any],
    schema: dict[str, Any],
) -> ValidationResult:
    """Basic validation of tool arguments against a JSON schema."""
    result = ValidationResult()

    required = schema.get("required", [])
    properties = schema.get("properties", {})

    for req in required:
        if req not in args:
            result.add_violation(f"Missing required argument: {req}")

    for key, value in args.items():
        if key not in properties:
            if schema.get("additionalProperties") is False:
                result.add_violation(f"Unknown argument: {key}")
            continue

        prop_schema = properties[key]
        expected_type = prop_schema.get("type")
        if expected_type:
            type_map: dict[str, type[Any] | tuple[type[Any], ...]] = {
                "string": str,
                "integer": int,
                "number": (int, float),
                "boolean": bool,
                "array": list,
                "object": dict,
            }
            python_type = type_map.get(expected_type)
            if python_type and not isinstance(value, python_type):
                result.add_violation(
                    f"Argument '{key}' should be {expected_type}, got {type(value).__name__}"
                )

        if expected_type == "string" and "enum" in prop_schema and value not in prop_schema["enum"]:
            result.add_violation(
                f"Argument '{key}' must be one of {prop_schema['enum']}, got '{value}'"
            )

    return result
