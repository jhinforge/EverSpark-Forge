# Concept Forge

Discussion, structured intent, schema validation, and prompt compilation.

The managed default is Qwen3 4B GGUF Q4_K_M imported into Ollama as
`everspark-concept`. On single-GPU systems the managed Ollama service unloads
the model after each request to hand memory back to Image Forge.

The current implementation contains:

- a provider-neutral chat contract and gateway, with an Ollama adapter registered through `Plugins/ollama.json`;
- the versioned `Character Subject v1` JSON Schema;
- strict local validation without third-party dependencies;
- deterministic subject-to-prompt compilation;
- protected document identity and sequential revisions;
- automatic extraction and update from the user/model conversation context.

Orchestrator talks to Concept Forge through the service. The gateway routes
normalized chat requests to a registered adapter; Ollama's `/api/chat` payload,
`/api/tags` model list, `/no_think` setting, and HTTP errors stay in its adapter.
Other providers can add their own input and output adapters without changing
the subject, discussion, or prompt compilation logic. Only Ollama is installed
as a Concept Forge provider in this release; the existing configuration remains valid.

## Character Subject v1

The schema is stored at `Schemas/character_subject.v1.schema.json`. It contains
only reusable character identity: identity, appearance, default wardrobe,
and metadata. Current data is stored under `Data/Subjects/<subject_id>/` as
`subject.json`, `metadata.json`, `positive_prompt.json`, and `negative_prompt.json`.
The prompt documents contain the complete last generated prompts, including
scene details. SQLite retains subject indices, session links, task records, and
revision history. Subjects can be viewed and revised by group through Concept
Forge in the WebUI, without editing JSON by hand. The initial negative prompt
is reused on later generations unless the user explicitly requests a negative
prompt change. The previous positive prompt is provided as context for the next
generation to carry reusable edits forward while updating its scene. Existing
SQLite subjects and v1 prompt contracts migrate on startup. Scene, pose, camera,
and background remain request-level state and are not persisted into the subject.
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
