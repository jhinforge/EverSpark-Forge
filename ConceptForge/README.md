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
- automatic extraction and update from the user/model conversation context.

Ollama remains an implementation provider: Orchestrator talks to the Concept
Forge interface and does not own Ollama HTTP behavior.

## Character Subject v1

The schema is stored at `Schemas/character_subject.v1.schema.json`. It contains
only reusable character identity: identity, appearance, default wardrobe,
and metadata. Positive and negative prompts are stored in a separate JSON
document per subject in SQLite (`subject_prompts`). The initial negative prompt
is reused on later generations unless the user explicitly requests a negative
prompt change. Existing v1 prompt contracts migrate on startup. Scene, pose, camera, and
background remain request-level state and are not persisted into the subject.
The schema is an internal contract, not a form the user is expected to fill.
For v0.1, each conversation automatically owns one current subject. Discussion
and generation turns both refresh it from the complete bounded context.

Developer and diagnostic commands can still create, validate, or compile a
document locally:

```bash
./everspark concept new character-id "Display Name"
./everspark concept validate subject.json
./everspark concept compile subject.json
```

`Examples/character_subject.example.json` is a complete public example.
`Examples/character_prompts.example.json` shows the independent prompt JSON.
