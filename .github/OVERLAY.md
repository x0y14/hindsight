# Overlay fork notes (`x0y14/hindsight`)

This fork tracks upstream release tags as `vX.Y.Z-ja` (Japanese temporal overlay).

## Releases

- Use tag pattern **`vX.Y.Z-ja` only**. Do **not** push bare `vX.Y.Z` tags.
- Do **not** run `scripts/release.sh` or the upstream `hs-release` skill on this fork (those cut PyPI/npm/`vX.Y.Z`).
- Image publish is [`.github/workflows/release-ja.yml`](workflows/release-ja.yml) only:
  - `ghcr.io/x0y14/hindsight-api:<X.Y.Z-ja>-slim`
  - `ghcr.io/x0y14/hindsight-api:latest-slim` (on tag push)

## Upstream follow

1. Branch from upstream `vX.Y.Z`
2. Cherry-pick JA feature commits
3. Cherry-pick **this CI overlay commit** (workflow deletes + `release-ja.yml`)
4. Confirm `git show HEAD:.github/workflows/release.yml` fails
5. Tag `vX.Y.Z-ja` and push `refs/tags/vX.Y.Z-ja`

Missing the CI overlay commit is a release blocker: a restored upstream `release.yml` would publish PyPI/npm/all images on the next `v*` tag.
