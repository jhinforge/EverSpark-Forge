# Portal

Portal serves the shared WebUI used by browsers and the Windows desktop client.
It uses Python's standard library and Aegis logging, with no frontend build step.
Start it through `everspark.cmd archon start` on Windows or the desktop EXE;
`./everspark webui start` is a Linux diagnostic entry requiring an available backend.

The sidebar has Creation, Asset library, Compute, Resources, Settings and About.
Portal owns UI presentation and HTTP proxies, not model execution or Node leases.
`app.py` routes `/api/*`; `static/app.js` handles interaction and polling;
`static/i18n.js` supplies Chinese/English copy. Forge resource/business routes
are delegated through Gate. Media result queries return file references/URLs;
remote media ZIP preparation returns a Node download URL.

`GET /api/about` reports local release metadata or source-checkout information.
It does not verify package authenticity. `GET /api/runtime/status` separates
Archon readiness from Concept/Image/Audio health; transient probe results do not
replace Node heartbeat state.

See [Usage](../../Docs/Usage.md), [Architecture](../../Docs/Architecture.md)
and [Troubleshooting](../../Docs/Troubleshooting.md). Tests: `Tests/WebUI/`.
