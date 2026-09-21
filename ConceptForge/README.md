# Concept Forge

Discussion, structured intent, schema validation, and prompt compilation.

The current migrated slice contains the Ollama provider used by the v0.1
generation chain. Ollama remains an implementation provider: Orchestrator
talks to the Concept Forge interface and does not own Ollama HTTP behavior.

The reusable target JSON schema and multi-turn subject builder are not part of
this migration batch and remain the next Concept Forge layer.
