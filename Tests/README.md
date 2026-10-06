# Tests

Tests live beside the repository source but do not ship in portable ZIPs.
Run from the repository root. Most Python cases use the standard unittest runner:

```bash
python -m unittest discover -s Tests/Client -p 'test_*.py'
python -m unittest discover -s Tests/Archon -p 'test_*.py'
python -m unittest discover -s Tests/WebUI -p 'test_*.py'
node --test Tests/WebUI/test_*.js
```

Other suites cover Configuration, Infrastructure/Storage, Orchestrator,
ConceptForge, AudioForge, Memory and Runtime (logging, managed lifecycle,
hardware and system). Inspect each suite's `run_tests.sh` when shell setup is
required. Python imports may require repository/module paths; the CI workflows
set the needed `PYTHONPATH` rather than copying tests into installed runtimes.

[Media regression](../.github/workflows/media-access.yml) defines the current
cross-module commands and covers distributed creation, media/archive URLs,
cloud storage, configuration and UI contracts.
[Windows portable client](../.github/workflows/windows-client.yml) checks backend
lifecycle, packaging, Rust and both ZIP startup paths using
`Tests/Client/smoke_windows.ps1`. Run the smoke on Windows with a built ZIP.

Automated deterministic Node/HTTP tests are not proof of real GPU compatibility,
provider networks, native Save As interaction or UI appearance. Use real Pods for
those acceptance checks; collect the version, task ID and logs on failure.
