# QC Maya Viewport

Blender extension by Mutaform Studio for matching a Maya-style viewport shading workflow.

## Compatibility

- Blender 5.1 or newer
- Packaged as a Blender Extension

## Install From Blender Repository

Add the extension repository URL in Blender:

```text
https://mutaform.github.io/qc-maya-viewport/index.json
```

Then sync repositories and search for `QC Maya Vieport`.

## Manual Install

1. Download the release ZIP from GitHub Pages or GitHub Releases.
2. In Blender, open `Edit > Preferences > Extensions`.
3. Use `Install from Disk`.
4. Select `maya_viewport_match.zip`.
5. Enable `QC Maya Vieport`.

## Build Release ZIP

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File tools/build_release.ps1
```

The release archive will be written to:

```text
dist/maya_viewport_match.zip
```

## Repository Layout

```text
maya_viewport_match/
  blender_manifest.toml
  __init__.py
  camera_sync.py
  coordinates.py
  custom_engine.py
  metadata.py
  operators.py
  state.py
  ui.py
tools/
  build_release.ps1
```

## License

This project is licensed under GPL-3.0-or-later, matching the Blender Extension manifest.
