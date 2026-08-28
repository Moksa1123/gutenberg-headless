# Releasing

npm publishing is driven by git tags — never run `npm publish` by hand.

## One-time setup

1. npmjs.com → profile → **Access Tokens** → Generate New Token → **Automation**
2. GitHub repo → Settings → Secrets and variables → Actions →
   **New repository secret** → name `NPM_TOKEN`, paste the token

## Every release

```bash
npm version patch          # or minor / major — bumps package.json, commits, tags vX.Y.Z
git push --follow-tags     # the tag triggers .github/workflows/publish.yml
```

The workflow refuses to publish when the tag and `package.json` disagree, and
runs the installer + validator smoke tests before `npm publish --provenance`.
Watch it: `gh run watch`.

## What "minor" means here

The package versions the **data as much as the code**. Re-extracting against a
newer WordPress (new blocks, changed attributes, new style properties) is at
least a minor bump — agents pin against this surface, and a silently changed
schema under a patch version is exactly the failure class this skill exists to
prevent.
