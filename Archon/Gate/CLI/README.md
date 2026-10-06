# Gate command-line entry

The root `everspark` shell wrapper routes Linux commands to this directory.
The root `everspark.cmd` invokes `archon.py` with portable Python when present,
otherwise the system Python. Windows supports `archon start` and configuration
import; Linux also retains managed single-machine commands.

`archon start` starts the control backend, NodeManager, Forge bindings and Portal.
It does not install GPU runtimes on the control host. Ctrl+C stops the CLI host.
The Windows desktop client calls this same composition and owns its children.

`configure` imports private files from `Archon/Vault/Import/` or an explicit
source directory, preserving input files. Full environment imports replace
`.env`. Do not commit imported files or generated private data.

Use the [command reference](../../../Docs/Commands.md) for supported commands,
[Getting started](../../../Docs/Getting-Started.md) for deployment and
[Configuration](../../../Docs/Configuration.md) for settings. CLI imports,
startup and lifecycle checks live under `Tests/Launcher/` and `Tests/Client/`.
