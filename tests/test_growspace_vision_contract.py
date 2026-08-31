"""Executable checks for the Growspace Vision V1 wire contract."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).parents[1]
CONTRACT_DIR = ROOT / "contracts" / "growspace-vision" / "v1"
OPENAPI_PATH = CONTRACT_DIR / "openapi.json"
FIXTURE_DIR = CONTRACT_DIR / "fixtures"


class ContractValidationError(ValueError):
    """Raised when a fixture does not satisfy the supported schema subset."""


class OpenApiFixtureValidator:
    """Validate the JSON Schema keywords used by this contract without dependencies."""

    def __init__(self, document: dict[str, Any]) -> None:
        self.document = document

    def validate(self, value: Any, schema: dict[str, Any], path: str = "$") -> None:
        if "$ref" in schema:
            self.validate(value, self._resolve(schema["$ref"]), path)
            return

        if "oneOf" in schema:
            matches = 0
            failures: list[str] = []
            for candidate in schema["oneOf"]:
                try:
                    self.validate(value, candidate, path)
                except ContractValidationError as err:
                    failures.append(str(err))
                else:
                    matches += 1
            if matches != 1:
                raise ContractValidationError(
                    f"{path}: expected exactly one oneOf match, got {matches}; "
                    f"failures={failures}"
                )
            return

        expected_type = schema.get("type")
        if expected_type is not None and not self._has_type(value, expected_type):
            raise ContractValidationError(
                f"{path}: expected {expected_type}, got {type(value).__name__}"
            )

        if "const" in schema and value != schema["const"]:
            raise ContractValidationError(
                f"{path}: expected constant {schema['const']!r}, got {value!r}"
            )
        if "enum" in schema and value not in schema["enum"]:
            raise ContractValidationError(
                f"{path}: {value!r} is not one of {schema['enum']!r}"
            )

        if expected_type == "object":
            self._validate_object(value, schema, path)
        elif expected_type == "array":
            self._validate_array(value, schema, path)
        elif expected_type == "string":
            self._validate_string(value, schema, path)
        elif expected_type in {"integer", "number"}:
            self._validate_number(value, schema, path)

    def _resolve(self, reference: str) -> dict[str, Any]:
        if not reference.startswith("#/"):
            raise ContractValidationError(
                f"unsupported external reference: {reference}"
            )
        node: Any = self.document
        for part in reference[2:].split("/"):
            node = node[part.replace("~1", "/").replace("~0", "~")]
        return node

    @staticmethod
    def _has_type(value: Any, expected_type: str) -> bool:
        if expected_type == "object":
            return isinstance(value, dict)
        if expected_type == "array":
            return isinstance(value, list)
        if expected_type == "string":
            return isinstance(value, str)
        if expected_type == "boolean":
            return isinstance(value, bool)
        if expected_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected_type == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        raise ContractValidationError(f"unsupported schema type: {expected_type}")

    def _validate_object(
        self, value: dict[str, Any], schema: dict[str, Any], path: str
    ) -> None:
        properties = schema.get("properties", {})
        missing = set(schema.get("required", [])) - value.keys()
        if missing:
            raise ContractValidationError(
                f"{path}: missing required keys {sorted(missing)}"
            )
        unknown = value.keys() - properties.keys()
        if schema.get("additionalProperties") is False and unknown:
            raise ContractValidationError(f"{path}: unknown keys {sorted(unknown)}")
        for key, item in value.items():
            if key in properties:
                self.validate(item, properties[key], f"{path}.{key}")

    def _validate_array(
        self, value: list[Any], schema: dict[str, Any], path: str
    ) -> None:
        if len(value) < schema.get("minItems", 0):
            raise ContractValidationError(f"{path}: too few items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise ContractValidationError(f"{path}: too many items")
        if schema.get("uniqueItems") and len(
            {json.dumps(v, sort_keys=True) for v in value}
        ) != len(value):
            raise ContractValidationError(f"{path}: items must be unique")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                self.validate(item, item_schema, f"{path}[{index}]")

    @staticmethod
    def _validate_string(value: str, schema: dict[str, Any], path: str) -> None:
        if len(value) < schema.get("minLength", 0):
            raise ContractValidationError(f"{path}: string is too short")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise ContractValidationError(f"{path}: string is too long")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            raise ContractValidationError(
                f"{path}: string does not match {schema['pattern']!r}"
            )

    @staticmethod
    def _validate_number(value: int | float, schema: dict[str, Any], path: str) -> None:
        if "minimum" in schema and value < schema["minimum"]:
            raise ContractValidationError(f"{path}: value is below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise ContractValidationError(f"{path}: value is above maximum")


class GrowspaceVisionContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = json.loads(OPENAPI_PATH.read_text())
        cls.schemas = cls.document["components"]["schemas"]
        cls.validator = OpenApiFixtureValidator(cls.document)
        cls.manifest = json.loads((FIXTURE_DIR / "manifest.json").read_text())

    def test_openapi_and_fixture_files_are_json(self) -> None:
        self.assertEqual(self.document["openapi"], "3.1.0")
        for path in FIXTURE_DIR.rglob("*.json"):
            with self.subTest(path=path):
                json.loads(path.read_text())

    def test_every_object_schema_is_closed(self) -> None:
        def visit(node: Any, path: str) -> None:
            if not isinstance(node, dict):
                return
            if node.get("type") == "object":
                self.assertIs(
                    node.get("additionalProperties"),
                    False,
                    f"object schema is not closed: {path}",
                )
            for key in ("properties",):
                for name, child in node.get(key, {}).items():
                    visit(child, f"{path}.{key}.{name}")
            for key in ("oneOf",):
                for index, child in enumerate(node.get(key, [])):
                    visit(child, f"{path}.{key}[{index}]")
            if isinstance(node.get("items"), dict):
                visit(node["items"], f"{path}.items")

        for name, schema in self.schemas.items():
            visit(schema, f"components.schemas.{name}")

    def test_valid_fixtures_satisfy_their_component_schemas(self) -> None:
        for fixture in self.manifest["valid"]:
            with self.subTest(fixture=fixture["file"]):
                value = json.loads((FIXTURE_DIR / fixture["file"]).read_text())
                self.validator.validate(value, self.schemas[fixture["schema"]])

    def test_invalid_fixtures_are_rejected(self) -> None:
        for fixture in self.manifest["invalid"]:
            with self.subTest(fixture=fixture["file"], reason=fixture["reason"]):
                value = json.loads((FIXTURE_DIR / fixture["file"]).read_text())
                with self.assertRaises(ContractValidationError):
                    self.validator.validate(value, self.schemas[fixture["schema"]])

    def test_request_metadata_has_only_the_permitted_fields(self) -> None:
        self.assertEqual(
            set(self.schemas["AnalyzeMetadata"]["properties"]),
            {
                "schema_version",
                "camera_id",
                "growspace_id",
                "captured_at",
                "light_state",
                "model_id",
                "model_version",
            },
        )
        self.assertEqual(
            set(self.schemas["AnalyzeMetadata"]["required"]),
            set(self.schemas["AnalyzeMetadata"]["properties"]),
        )

    def test_response_schema_contains_no_forbidden_evidence_or_temporal_fields(
        self,
    ) -> None:
        forbidden = {
            "symptoms",
            "chlorosis",
            "drooping",
            "anomaly_score",
            "change_score",
            "trend",
            "vpd",
            "temperature",
            "humidity",
        }

        visited_refs: set[str] = set()

        def property_names(node: Any) -> set[str]:
            if not isinstance(node, dict):
                return set()
            reference = node.get("$ref")
            if reference:
                if reference in visited_refs:
                    return set()
                visited_refs.add(reference)
                return property_names(self.validator._resolve(reference))
            names = set(node.get("properties", {}))
            for child in node.values():
                if isinstance(child, dict):
                    names |= property_names(child)
                elif isinstance(child, list):
                    for item in child:
                        names |= property_names(item)
            return names

        response_names = property_names(self.schemas["AnalyzeResponse"])
        self.assertFalse(forbidden & response_names)

    def test_response_union_enforces_embedding_presence_by_status(self) -> None:
        analyzed = self.schemas["AnalyzedResponse"]
        rejected = self.schemas["RejectedResponse"]
        self.assertIn("embedding", analyzed["required"])
        self.assertNotIn("embedding", rejected["properties"])
        self.assertEqual(
            self.schemas["EmptyRegions"]["maxItems"],
            0,
        )

        fixture = json.loads(
            (FIXTURE_DIR / "valid" / "analyze-response-analyzed.json").read_text()
        )
        self.assertEqual(fixture["embedding"]["dimension"], 384)
        self.assertEqual(
            fixture["embedding"]["dimension"], len(fixture["embedding"]["values"])
        )

    def test_routes_authentication_and_cardinality_are_locked(self) -> None:
        self.assertEqual(
            set(self.document["paths"]), {"/health", "/info", "/models", "/analyze"}
        )
        self.assertEqual(self.document["paths"]["/health"]["get"]["security"], [])
        self.assertEqual(self.document["security"], [{"bearerAuth": []}])
        request_schema = self.schemas["AnalyzeRequest"]
        self.assertEqual(set(request_schema["properties"]), {"metadata", "image"})
        self.assertFalse(
            self.schemas["Capabilities"]["properties"]["batch_analysis"]["const"]
        )
        self.assertFalse(
            self.schemas["Capabilities"]["properties"]["service_scoring"]["const"]
        )

    def test_versions_limits_and_error_codes_are_locked(self) -> None:
        self.assertEqual(self.schemas["SchemaVersion"]["const"], 1)
        limits = self.schemas["OperationalLimits"]["properties"]
        self.assertEqual(limits["max_image_bytes"]["const"], 10 * 1024 * 1024)
        self.assertEqual(limits["max_decoded_pixels"]["const"], 24_000_000)
        self.assertEqual(limits["max_concurrency"]["const"], 1)
        self.assertEqual(limits["max_queue_depth"]["const"], 0)
        self.assertEqual(limits["inference_timeout_seconds"]["const"], 10)
        self.assertEqual(
            set(self.schemas["ErrorDetail"]["properties"]["code"]["enum"]),
            {
                "unauthorized",
                "unsupported_image_format",
                "image_too_large",
                "invalid_request",
                "unsupported_schema_version",
                "model_not_loaded",
                "busy",
                "internal_failure",
            },
        )
        self.assertEqual(
            {
                name: response["x-error-codes"]
                for name, response in self.document["components"]["responses"].items()
            },
            {
                "Unauthorized": ["unauthorized"],
                "ImageTooLarge": ["image_too_large"],
                "UnsupportedImageFormat": ["unsupported_image_format"],
                "UnprocessableRequest": [
                    "invalid_request",
                    "unsupported_schema_version",
                ],
                "Busy": ["busy"],
                "InternalFailure": ["internal_failure"],
                "ModelNotLoaded": ["model_not_loaded"],
            },
        )


if __name__ == "__main__":
    unittest.main()
