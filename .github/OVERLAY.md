# Overlay fork notes (`x0y14/hindsight`)

This fork tracks upstream release tags as `vX.Y.Z-ja` (Japanese temporal overlay).

## Releases

- Use tag pattern **`vX.Y.Z-ja` only**. Do **not** push bare `vX.Y.Z` tags.
- Do **not** run `scripts/release.sh` or the upstream `hs-release` skill on this fork (those cut PyPI/npm/`vX.Y.Z`).
- Image publish is [`.github/workflows/release-ja.yml`](workflows/release-ja.yml) only:
  - `ghcr.io/x0y14/hindsight-api:<X.Y.Z-ja>-slim` (OCI index: `linux/amd64` + `linux/arm64`; JA probe and morph Tagger() probe are amd64 only)
  - `ghcr.io/x0y14/hindsight-api:latest-slim` (same index digest; always on tag push; on `workflow_dispatch`, only when `update_latest` is true, default false)
- This is **`hindsight-api`** (`Dockerfile` target `api-only` slim). Official compose/bots pull `ghcr.io/vectorize-io/hindsight` (`standalone` = API+UI). Do **not** retag the api-only digest as `hindsight:…`; override compose `image:` to `hindsight-api:<X.Y.Z-ja>-slim` instead.
- Tag-push runs also keyless-sign the **index** digest. Rebuilds via `workflow_dispatch` publish but do **not** sign (consumers should trust tag-push signatures only).
- Privileged publish/sign jobs pin third-party actions by full commit SHA (QEMU also pins `tonistiigi/binfmt` by digest). `guard` / `test` may keep `actions/*@vN` because they only have `contents: read`.

## Upstream follow (file-based; do not key on a single CI commit SHA)

1. Branch from upstream `vX.Y.Z`.
2. Ensure the JA payload is present:
   - `hindsight-api-slim/hindsight_api/engine/japanese_temporal_periods.py`
   - `hindsight-api-slim/hindsight_api/engine/japanese_morph_tokens.py`
   - `hindsight-api-slim/pyproject.toml` optional extra `ja-morph` (`fugashi==1.5.2`, `unidic-lite==1.0.8`) — not in `all` / `test` / required deps
   - root `uv.lock` (locked with the extra)
   - `docker/standalone/Dockerfile` api-builder: **all four** `uv sync` lines include `--extra ja-morph` (local-ml on/off × deps layer / package layer). An exact sync without the extra uninstalls UniDic.
   - Chinese shared-form patches used by the JA router
   - Tests exercised by the release workflow (`tests/test_query_analyzer.py`, `tests/test_temporal_extraction.py`, `tests/test_japanese_morph_snapshot.py`)
   - In-image probe in `release-ja.yml` must construct `Tagger()` and assert natural-language extracts (`先週何について考えてた？` → DateRange, `きのうえに猫がいる` → None), not a mere `import fugashi`. Morph probe is **amd64 only**, same as the load step.
   - UniDic-lite is BSD-2-Clause; the image bundles it via the extra. Do **not** vendor the dictionary into `hindsight_api/`. Leave the installed package `LICENSE` in the image; release notes must mention the bundled dictionary.
3. Ensure the CI overlay files are present (workflow deletes + `release-ja.yml` + this note). Do **not** restore upstream publish workflows.
4. Workflows **allowlist** on the commit you will tag:
   - `.github/workflows/` contains **only** `release-ja.yml` (no `.yaml`, no extras)
   - `git show HEAD:.github/workflows/release.yml` must fail
   - Deleted upstream names (must stay absent): `deploy-docs.yml`, `perf-test.yml`, `release-integration.yml`, `release-tool.yml`, `release.yml`, `sign-images.yml`, `star-history.yml`, `test.yml`, `windows-smoke.yml`
5. Before tagging, check existing overlay tags: `git ls-remote origin 'refs/tags/v*-ja'`. Retagging an older `v*-ja` while a newer one exists will move `latest-slim` backward.
6. Tag and push only: `git tag -a vX.Y.Z-ja <commit>` then `git push origin refs/tags/vX.Y.Z-ja`.
7. Do **not** also `workflow_dispatch` in the same window as the tag push.

Missing the CI overlay (especially a restored upstream `release.yml`) is a release blocker: that workflow matches `v*` and would publish PyPI/npm/all images on the next `v*-ja` tag. An in-job allowlist cannot stop a sibling workflow.
