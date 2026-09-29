# Node Agent trial (Windows host + Vast Pod)

This is an opt-in, one-Pod trial. The existing SSH deployment path remains the
default. No Tailscale credential is stored in this repository or in `.env`.

1. Install Tailscale on the Windows host and sign in. Generate a **one-off**, 
   **ephemeral**, **pre-approved** auth key tagged `tag:everspark-node` for the
   Pod. Set a tailnet policy that permits the Pod tag to reach only this host's
   TCP port 8766. The host remains the only machine allowed to use the WebUI.
2. In the same PowerShell window that will start Archon, set the key for this
   launch only, then start Archon as usual:

   ```powershell
   $env:EVERSPARK_TAILSCALE_AUTH_KEY = Read-Host "One-off Tailscale auth key"
   .\everspark.cmd archon start
   ```

3. Rent **one new** Vast Pod in WebUI. The Pod's `onstart` installs Tailscale,
   uses userspace networking (no `/dev/net/tun` required), then starts the
   Node Agent. The machine card shows `Node Agent: Joining`, then `Online`.
   Deploy and test Concept Forge from that card. For the agent path the job
   stage is `agent_execution`; the Pod pulls allowlisted tasks from Archon.

Each key is used for at most one rental. For another agent Pod, generate a new
key and restart Archon with it. Already rented Pods use the SSH path; an agent
Pod will not be restored as an agent after the Archon process restarts in this
trial. The Pod startup log is `/workspace/everspark-node.log`; local task logs
are in `Archon/Steward/DeploymentManager/deployment.log`. Never paste keys or
the Pod's environment variables into issue reports.
