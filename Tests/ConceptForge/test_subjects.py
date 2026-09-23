from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "ConceptForge"))

from concept_forge.providers.ollama import OllamaProvider  # noqa: E402
from concept_forge.subjects import (  # noqa: E402
    SubjectValidationError,
    compile_subject,
    new_subject,
    update_subject,
    validate_subject,
)


EXAMPLE_PATH = (
    REPO_ROOT / "ConceptForge" / "Examples" / "character_subject.example.json"
)


class SubjectSchemaTests(unittest.TestCase):
    def test_example_and_blank_template_are_valid(self) -> None:
        example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        self.assertIs(validate_subject(example), example)
        blank = new_subject("test-subject", "Test Subject")
        self.assertEqual(blank["revision"], 1)
        self.assertEqual(blank["subject_id"], "test-subject")

    def test_unknown_fields_and_invalid_ids_are_rejected(self) -> None:
        document = new_subject("valid-id", "Valid")
        document["unexpected"] = True
        with self.assertRaises(SubjectValidationError):
            validate_subject(document)
        with self.assertRaises(SubjectValidationError):
            new_subject("Invalid ID", "Invalid")

    def test_update_increments_revision_and_protects_identity(self) -> None:
        document = new_subject("subject-a", "Subject A")
        updated = update_subject(
            document,
            {
                "appearance": {
                    "hair": {"color": "silver", "length": "long"}
                }
            },
        )
        self.assertEqual(updated["revision"], 2)
        self.assertEqual(updated["appearance"]["hair"]["color"], "silver")
        self.assertEqual(updated["appearance"]["hair"]["style"], "")
        with self.assertRaisesRegex(ValueError, "protected"):
            update_subject(document, {"subject_id": "changed"})


class SubjectCompilerTests(unittest.TestCase):
    def test_example_compiles_stable_positive_and_negative_fragments(self) -> None:
        document = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        compiled = compile_subject(document)
        self.assertEqual(compiled.subject_id, "ember-keeper")
        self.assertIn("amber sharp eyes", compiled.positive_prompt)
        self.assertIn("waist-length black straight hair", compiled.positive_prompt)
        self.assertIn("black high-collar coat", compiled.positive_prompt)
        self.assertEqual(
            compiled.negative_prompt,
            "different hair color, different eye color",
        )


class OllamaSubjectBuilderTests(unittest.TestCase):
    def test_subject_extraction_receives_user_and_model_conversation(self) -> None:
        document = new_subject("auto-subject", "Current Character")
        provider = OllamaProvider(
            {"base_url": "http://127.0.0.1:11434", "model": "test", "timeout": 1}
        )
        with patch.object(
            provider,
            "_post_json",
            return_value={"message": {"content": json.dumps(document)}},
        ) as post:
            provider.generate_subject(
                "Make her eyes amber",
                "auto-subject",
                history=[
                    {"role": "user", "content": "She has black hair"},
                    {"role": "assistant", "content": "A long style would suit her."},
                ],
                assistant_reply="Amber eyes are now part of the design.",
            )
        extraction_request = post.call_args.args[1]["messages"][-1]["content"]
        self.assertIn("She has black hair", extraction_request)
        self.assertIn("A long style would suit her", extraction_request)
        self.assertIn("Amber eyes are now part of the design", extraction_request)

    def test_provider_requires_the_fixed_subject_contract(self) -> None:
        document = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
        provider = OllamaProvider(
            {"base_url": "http://127.0.0.1:11434", "model": "test", "timeout": 1}
        )
        with patch.object(
            provider,
            "_post_json",
            return_value={"message": {"content": json.dumps(document)}},
        ):
            result = provider.generate_subject(
                "Create an ember keeper", "ember-keeper"
            )
        self.assertEqual(result, document)

        broken = dict(document)
        broken["extra"] = "not allowed"
        with patch.object(
            provider,
            "_post_json",
            return_value={"message": {"content": json.dumps(broken)}},
        ):
            with self.assertRaisesRegex(RuntimeError, "not allowed"):
                provider.generate_subject("Create", "ember-keeper")

    def test_provider_stamps_orchestrator_owned_subject_metadata(self) -> None:
        existing = new_subject("auto-subject", "Current Character")
        existing["revision"] = 6
        model_document = json.loads(json.dumps(existing))
        model_document["schema_version"] = "model-owned"
        model_document["document_type"] = "model-owned"
        model_document["subject_id"] = "wrong-subject"
        model_document["revision"] = 5
        model_document["appearance"]["hair"]["color"] = "black"
        provider = OllamaProvider(
            {"base_url": "http://127.0.0.1:11434", "model": "test", "timeout": 1}
        )
        with patch.object(
            provider,
            "_post_json",
            return_value={"message": {"content": json.dumps(model_document)}},
        ):
            result = provider.generate_subject(
                "Keep her black hair", "auto-subject", existing
            )

        self.assertEqual(result["schema_version"], "1.0")
        self.assertEqual(result["document_type"], "character_subject")
        self.assertEqual(result["subject_id"], "auto-subject")
        self.assertEqual(result["revision"], 7)
        self.assertEqual(result["appearance"]["hair"]["color"], "black")

    def test_no_think_mode_is_added_to_system_prompt(self) -> None:
        provider = OllamaProvider(
            {
                "base_url": "http://127.0.0.1:11434",
                "model": "everspark-concept",
                "prompt_mode": "no_think",
            }
        )
        with patch.object(
            provider,
            "_post_json",
            return_value={
                "message": {
                    "content": json.dumps(
                        {
                            "model": "illustrious",
                            "positive_prompt": "portrait",
                            "negative_prompt": "low quality",
                            "count": 1,
                            "status": "over",
                        }
                    )
                }
            },
        ) as post:
            provider.generate_prompt("draw")
        system_prompt = post.call_args.args[1]["messages"][0]["content"]
        self.assertTrue(system_prompt.rstrip().endswith("/no_think"))


if __name__ == "__main__":
    unittest.main()
