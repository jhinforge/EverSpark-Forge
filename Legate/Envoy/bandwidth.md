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
package (`speedtest.md`). EverSpark does not pass acceptance flags without a recorded user confirmation.

If the tool requires confirmation, the machine's network area displays links to
Ookla's license, terms of use and privacy policy. The checkbox starts unchecked.
After reviewing the terms, users can check the agreement and click **Confirm
and start network test**. No SSH session is needed.

The existing `/api/nodes/bandwidth` route accepts an optional boolean
`accept_terms`. Only explicit `true` routes the allowlisted
`accept_ookla_terms` task message to the selected Node. The Node saves a
versioned, per-Pod confirmation in `ookla-consent.json` and runs the official
CLI with `--accept-license --accept-gdpr`. Automatic tests and retests reuse
that confirmation; changing CLI version requires a new confirmation. Ordinary
requests without this field do not create confirmation records. Existing
confirmations from manual CLI tests remain usable by the official tool.

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
