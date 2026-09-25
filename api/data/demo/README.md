# Demo fixtures

Small, curated responses served when `DEMO_MODE=true`. This folder **is committed**.

- One file per fixture: `<key>.json`, where the key matches `^[A-Za-z0-9_-]+$` and follows
  `<module>__<resource>[__<ts>]` (`shared/contracts.md` §7), e.g.:
  - `hazard__layers-surge__20200520T1200Z.json`
  - `exposure__infra-power-line.json`
  - `risk__scores__20200520T1200Z.json`
- Load with `app.core.demo.load_fixture("<key>")`.
- Every file here is validated against its contract schema by `tests/test_demo_fixtures.py`.
- Keep files small. Anything large or regenerable goes in `data/cache/` (ignored scratch).
