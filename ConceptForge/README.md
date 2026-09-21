# Concept Forge

Discussion, structured intent, schema validation, and prompt compilation.

The managed default is Qwen3 4B GGUF Q4_K_M imported into Ollama as
`everspark-concept`. On single-GPU systems the managed Ollama service unloads
the model after each request to hand memory back to Image Forge.

The current implementation contains:

- the Ollama provider used by the v0.1 generation chain;
- the versioned `Character Subject v1` JSON Schema;
- strict local validation without third-party dependencies;
- deterministic subject-to-prompt compilation;
- protected document identity and sequential revisions;
- model-assisted creation and update against the same fixed contract.

Ollama remains an implementation provider: Orchestrator talks to the Concept
Forge interface and does not own Ollama HTTP behavior.

## Character Subject v1

The schema is stored at `Schemas/character_subject.v1.schema.json`. It contains
only reusable character identity: identity, appearance, default wardrobe,
locked/flexible traits, prompt terms, and metadata. Scene, pose, camera, and
background remain request-level state and are not persisted into the subject.

Create, validate, or compile a document locally:

```bash
./everspark concept new character-id "Display Name"
./everspark concept validate subject.json
./everspark concept compile subject.json
```

`Examples/character_subject.example.json` is a complete public example.
