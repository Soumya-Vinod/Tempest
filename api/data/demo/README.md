# Demo fixtures

Small, curated responses served when `DEMO_MODE=true`. This folder **is committed**.

- One file per fixture: `<key>.json`, where the key matches `^[a-z0-9_-]+$`
  (e.g. `amphan_track.json`).
- Load with `app.core.demo.load_fixture("<key>")`.
- Keep files small. Anything large or regenerable goes in `data/cache/` (ignored scratch).
