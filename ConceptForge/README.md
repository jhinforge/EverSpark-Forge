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
the subject, discussion, or prompt compilation logic. Ollama remains the built-in
default. OpenAI Compatible connections can be added under **Model services** in
the WebUI sidebar. Enter a connection name, an API base URL ending in `/v1`,
the provider's exact model ID, and its API Key. Test before using it, then choose
the service and model in Forge, or set it as the default for subject revisions.
Connection tests run as background jobs so a slow model response does not hold
the WebUI request open; the page polls for the result and displays provider errors.
The adapter sends non-streaming Chat Completions requests. Optional JSON mode
is disabled by default for services that do not implement `response_format`.
Connections persist under `Data/Configuration/ConceptForge/connections.json`
with owner-only file permissions; API keys are never returned by the WebUI API.

## Character Subject v1

The schema is stored at `Schemas/character_subject.v1.schema.json`. It contains
only reusable character identity: identity, appearance, default wardrobe,
and metadata. Current data is stored under `Data/Subjects/<subject_id>/` as
`subject.json`, `metadata.json`, `positive_prompt.json`, and `negative_prompt.json`.
The prompt documents contain the complete last generated prompts, including
scene details. SQLite retains subject indices, session links, task records, and
revision history. Subjects can be viewed and revised by group through Concept
Forge in the WebUI, without editing JSON by hand. On the first generation,
the selected image plugin's default negative terms and Concept Forge's generated
terms form the saved negative prompt, with duplicate terms removed. ComfyUI
reads its defaults from the selected API workflow; Diffusers supplies its SDXL
defaults. The saved negative prompt is reused on later generations, even after
switching drawing tools, unless the user explicitly requests a change. The
previous positive prompt is provided as context for the next
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
