# Audio Forge

VoxCPM2 speech synthesis uses the official OpenBMB/VoxCPM source pinned in
`requirements.txt` to commit `f0c787f0937dc1c9a8f4f64d9a332d9c5da2e629`
(2026-09-30; latest upstream main checked on 2026-10-01).
Installation never follows a moving branch. This source revision is newer than
the PyPI 2.0.3 release; it is identified by commit, not a fabricated release number.

Deploy or redeploy Audio Forge on its selected node after updating EverSpark.
The installer upgrades the isolated audio environment and checks the installed
Git source and full commit through pip's `direct_url.json` before downloading models.
The health check enforces the same pin and matching Torch/torchaudio CUDA builds.

The Forge instruction remains `text` plus optional `voice_description`.
The adapter uses upstream's Python API and Voice Design `(description)text`
format, also used by the upstream CLI. Model weights are downloaded separately
from the configured `OpenBMB/VoxCPM2` model repository; this source pin does not
pin model weights or every transitive dependency.
