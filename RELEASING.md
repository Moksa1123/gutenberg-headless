# Releasing

npm publishing is driven by git tags — never run `npm publish` by hand.

## One-time setup (done)

No token anywhere: npmjs.com → package **Settings** → **Trusted Publisher** →
GitHub Actions, `Moksa1123/gutenberg-headless`, workflow `publish.yml`. The
workflow authenticates via OIDC (`id-token: write`); provenance is automatic.

## Every release

```bash
npm version patch          # or minor / major — bumps package.json, commits, tags vX.Y.Z
git push --follow-tags     # the tag triggers .github/workflows/publish.yml
```

The workflow refuses to publish when the tag and `package.json` disagree, and
runs the installer + validator smoke tests before the OIDC `npm publish`.
Watch it: `gh run watch`.

## What "minor" means here

The package versions the **data as much as the code**. Re-extracting against a
newer WordPress (new blocks, changed attributes, new style properties) is at
least a minor bump — agents pin against this surface, and a silently changed
schema under a patch version is exactly the failure class this skill exists to
prevent.
