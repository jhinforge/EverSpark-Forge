# Updating

The client, host and Nodes run in separate locations. Updating one does not automatically update the others. See [Getting started](Getting-Started.md).

## Before updating

Wait for deployments, generation, transfers and downloads to finish, then close the host. Export characters/Memory, preserve Pod outputs and back up private settings. Record the version/commit from About. Recheck credentials and Node bindings after upgrading; source backups are not user-data backups.

## Windows portable client

1. Obtain the new standard or full package from the official distribution entry and compare its published checksum.
2. Close the old client and fully extract the new package into a new directory. Keep the old directory for rollback. Do not replace only the EXE or Python.
3. To retain data on the same computer, copy the old `.env` and required `Data/` while stopped, or restore characters/Memory through a data ZIP. Transfer private settings separately. Do not overwrite new `Runtime/` or source files. The optional browser profile also lives in Data; do not force reuse if it fails.
4. Start the new client and check About, accounts, Node bindings, cloud configuration and creation.

This Windows user's Vast credentials and default `%LOCALAPPDATA%/EverSpark/` state are outside the ZIP. Reconfigure on a different computer. The rental Tailscale auth key is session-only; enter it again before new rentals. See [Runtime and data](Runtime-and-Data.md).

## Windows source host

Stop the running host and execute at the repository root:

```powershell
git status
# With a clean worktree, or after separately preserving your changes:
git pull --ff-only origin refactor/distributed-architecture
.\everspark.cmd archon start
```

If fast-forward fails, resolve local commits or branch divergence; do not force-reset away your work. This command targets the current development branch. After a formal release, use the branch/tag specified in its release notes.

## Existing Pods

Host upgrades do not automatically update existing Pod code and running processes. Use the machine card's deployment/redeployment flow for the affected Forge, then verify source and service health before selecting it.

The Agent, model-storage service and media URL service are separate processes. Restarting only the Agent does not guarantee that a persistent model-storage process reloads updated code. After Node source updates, restart affected model-storage/media services. During maintenance, a Pod restart is an alternative after preserving outputs and confirming no active jobs; verify Forges afterwards. Update Audio dependencies through Audio redeployment, not another Forge's environment.

Process restarts may lose in-memory task state. Do not automatically resubmit a task whose outcome is unknown. See [Troubleshooting](Troubleshooting.md) for version mismatches and unknown outcomes.

## Linux single-machine mode

Stop managed services, preserve private data and update source. Run setup/start as required by the release. Preview installation with `setup --plan`. Reinstalling runtimes does not restore user data.

## After updating

Check startup, existing Node reconnection, Forge health, one generation and download. Rollback also requires compatible data backups. Never let two hosts write the same database together.
