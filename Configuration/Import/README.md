# Private configuration inbox

Upload private configuration files into this directory before setup:

- `env.txt` or `.env`
- `rclone.conf` when using an existing rclone/R2 connection
- `<CF_TUNNEL_UUID>.json` when using a Cloudflare Named Tunnel

Then run from the repository root:

```bash
./everspark configure
```

EverSpark validates and copies the files into its ignored managed locations.
The source files remain here. Everything in this directory except this README
is ignored by Git and must never be committed.
