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
