# Optional Node network test

The background worker uses the official Ookla Speedtest CLI 1.2.0 on Linux
x86_64 / aarch64. It first checks its private installation, the manual test
installation at `/tmp/everspark-ookla-test/speedtest`, and an official CLI on
PATH. If none is available, it downloads a private copy from
`https://install.speedtest.net` into the Node data directory. The repository
does not redistribute the binary. Python `speedtest-cli` is not used.

## First use

The official tool has its own license and privacy terms, independently of
EverSpark's license. Review them at the prompts or the links in the official
package (`speedtest.md`). EverSpark does not pass `--accept-license` or
`--accept-gdpr` on behalf of users.

If the tool requires confirmation, the UI displays a terms-required message
and Details includes the command to run over SSH. Run that executable
interactively as the same user as the Node Agent, review the prompts, and
confirm only if you agree. Then retry in WebUI. Existing confirmations from
manual CLI tests are reused by the official tool.

## Execution and interpretation

- Registration schedules one optional test. Manual retest uses the existing
  `/api/nodes/bandwidth` task route and heartbeat result channel.
- Only one worker runs per Node. Successful completion has a 20-second retest
  cooldown. Every retest gets a new result file state, so old speeds cannot be
  displayed as the result of a failed run.
- Ookla selects the server and download/upload durations. Each invocation is
  limited to 90 seconds; an execution failure is retried once after 2 seconds.
  Terms confirmation failures are not retried.
- CLI JSON bandwidth is bytes/second and transfer elapsed time is milliseconds.
  WebUI uses decimal MB/s, with 50 MB/s as a reference target, not an admission
  requirement. Network test speeds are not model-source or cloud-storage speeds.
- The result retains server name/ID/city/country, download/upload rates, download
  bytes/duration, latency, jitter and optional packet loss. Server country is not
  treated as the Node's country. Raw results, client IP/MAC, ISP and result URLs
  are not persisted or forwarded to Archon.
- A failed test has no speed value and does not affect registration, deployment
  or generation. Logs are in `bandwidth.log`, with state in `bandwidth.json`
  under the Node data directory (normally `/workspace/everspark-node`).
- The test transfers both download and upload traffic. `EVERSPARK_NODE_BANDWIDTH=0`
  disables the optional worker. Previous measurement formats remain readable.

CLI information: <https://www.speedtest.net/apps/cli>.
