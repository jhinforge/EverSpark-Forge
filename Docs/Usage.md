# Daily usage

For initial deployment see [Getting started](Getting-Started.md). This guide follows the current sidebar.

## Creation

Discuss mode creates and edits reusable characters. Generate mode accepts this request's scene and speech. Choose Image, Audio or Image + audio and check the required Forge Nodes and model service. Explicit dialogue is preserved by default; request translation or rewriting explicitly.

Image options include the selected Node's workflows, checkpoints, LoRAs and VAEs. Recheck resources after switching Nodes. Model and LoRA compatibility depends on the workflow. Registered workflows require a supported API Format file and adjacent manifest; a normal ComfyUI UI JSON is not directly executable as a registered workflow.

Task rows show the Forge, execution Node and state of each step. The current runner follows dependencies; separate machines do not automatically imply parallelism. Check skipped steps after a failure rather than treating one completed step as whole-request success.

## Asset library

- **Characters**: select, use and inspect revisions. A listed character is not necessarily selected in the current conversation.
- **Images / Audio**: inspect history, play audio, download individual files or separate image and audio ZIPs.
- **Data backup**: export a character/Memory ZIP or validate and restore one. Restart the host after restoration.

Each image or audio ZIP belongs to its corresponding selected Forge Node. It does not merge all history across Nodes. Desktop downloads open Save As, then download directly from the Pod, with a completion message showing the actual path. Browsers use their download preferences. Output export does not back up characters, models or credentials; see [Runtime and data](Runtime-and-Data.md).

## Compute

My machines manages instances, Nodes, Forge deployment and selection. Rent GPU searches offers and rents instances. Runtime status reports Archon and Forge health. An online Node heartbeat and a healthy Forge are separate conditions.

Optional network tests use the official Ookla CLI. First-use confirmation is available in the UI, without manual SSH. Results describe a speed-test server route, not guaranteed model-source or storage performance. Failure does not block creation. See [Node network testing](../Legate/Envoy/bandwidth.md).

## Resources and Settings

**Resources** provides direct model downloads and cloud model scanning/pulling. Downloads target the selected Image or Concept Node and do not migrate after a Node selection change. Audio deployment prepares Audio weights; do not treat them as Image or Concept resources.

**Settings** manages model APIs, Vast/Tailscale and cloud storage. Image and Concept cloud directories can be configured independently; see [Configuration](Configuration.md).

**About** displays Jhin, the free-software statement, official repository, version, build time and commit. Source checkouts may lack build time. The page is not cryptographic authentication of a package.
