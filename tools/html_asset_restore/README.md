# Base64 HTML/template restore

Some download or content-filtering paths rewrite Gitea template markup. This directory stores an independent base64 representation of every `templates/**/*.tmpl` file, together with its expected byte size, mode and SHA-256 digest.

## After cloning or extracting the source

Run from the repository root:

```bash
python3 restore.py
python3 restore.py --check
```

`restore.py` decodes each payload, verifies its size and SHA-256 digest, then atomically replaces the corresponding source file. It refuses absolute paths and paths that escape the repository or payload directory.

Useful options:

```bash
python3 restore.py --dry-run
python3 restore.py --only 'templates/admin/auth/*.tmpl'
python3 restore.py --check --only 'templates/admin/auth/edit.tmpl'
```

## Refreshing the payload

After intentionally changing a template, regenerate the payload locally:

```bash
python3 tools/html_asset_restore/pack.py
```

Then commit `tools/html_asset_restore/manifest.json` and `tools/html_asset_restore/payload/*.b64` together with the template change.

The `refresh-html-asset-payload.yml` workflow performs the same operation automatically whenever templates or the packer change on the protected fork branch.

Only Python's standard library is required.
