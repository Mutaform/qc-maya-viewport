# QC Maya Viewport

Blender extension by Mutaform Studio for matching a Maya-style viewport shading workflow.

## Find Textures

`Find Textures` in the viewport header popover fills the active material from a
folder of texture files.

1. Select the object and the material slot.
2. Press `Find Textures`. The browser opens on that object's own asset folder.
3. Pick the folder that holds the maps and press Accept.

### Where the browser opens

Blender does not keep the path an object was imported from, so the folder is
worked out per object, in this order:

1. The file the object was imported from, if the import happened while this
   add-on was enabled — it records the path on the object as `mvm_source`.
2. The folder of a texture the material already uses.
3. **A search by name under the project roots.** An object called
   `SM_Cookware_Shelf_01` finds `.../SM_Cookware_Shelf_01/`, then the subfolder
   inside it that actually holds textures. The object, mesh and material names
   are all tried, and a hit inside a `Meshes` subfolder climbs out to where the
   maps really are.
4. The folder of the saved `.blend`.

Project roots are set in `Settings` and default to nothing, so add the drive
your assets live on (for example the review or projects folder). Results are
cached for the session.

Files are sorted by the suffix on their name, then linked to the Principled
BSDF:

| Suffix | Goes to |
| --- | --- |
| `_COL` `_BaseColor` `_Albedo` `_Diffuse` `_D` `_C` | Base Color |
| `_Normal` `_NM` `_N` `_Normal_OpenGL` `_Normal_DX` | Normal Map |
| `_NRM` | Normal XY + Roughness (see below) |
| `_Roughness` `_Rough` `_R` | Roughness |
| `_Metallic` `_Metalness` `_M` | Metallic |
| `_AO` `_Occlusion` | AO (viewport AO modes) |
| `_Height` `_Displacement` `_Bump` `_H` | Bump |
| `_Emissive` `_Emission` `_E` | Emission Color |
| `_Opacity` `_Alpha` `_Mask` | Alpha |
| `_Spec` `_Specular` | Metalness / Roughness / AO (studio packing) |
| `_ORM` `_MRO` `_RMA` `_ARM` … | Split into its channels by the letters |

Ignored on purpose, never wired into the shader: `_cc` (tint-mapping mask),
`_curve`, `_cavity`, `_thickness`, `_objid`, `_matid`, `_position`, `_id`.

`_NRM` is the studio delivery format: **R = Normal X, G = Normal Y, B =
Roughness**. It is unpacked through a `MVM Unpack NRM` node group that rebuilds
Z as `sqrt(1 - x² - y²)` and sends blue to Roughness. The QC viewport rebuilds
the same Z on the GPU. When a plain `_Normal` and `_Roughness` sit in the same
folder they win and the `_NRM` file is left alone.

A file with **no suffix at all** counts as the base color when a suffixed
sibling with the same name sits beside it (`Voron_cabin.tga` next to
`Voron_cabin_nm.tga`). When a set has an `_AO` map but nothing to put in the
diffuse, the AO map is linked to Base Color.

Data maps get `Non-Color`, height goes through a Bump node on top of the normal,
and a filename that spells out OpenGL or DirectX sets the Normal Map node's
convention as well as the viewport's. The `OpenGL` / `DirectX` buttons in the
popover switch both together for the whole scene, so EEVEE and Cycles match
what the QC viewport shows.
Textures already in the material are repointed rather than duplicated, `.psd`
files only win when nothing else carries the same map, and a file in the chosen
folder beats the same file in a subfolder (so `Marmoset/` wins over
`Marmoset/1k/`).

When several texture sets share one folder, the file whose name matches the
material is used, so `MI_Chair_Wood` takes `T_Chair_Wood_*` and leaves
`T_Chair_Metal_*` alone. When nothing matches the material name, whatever the
folder holds is assigned instead.

Options in the file browser sidebar: search subfolders, match material name,
fill every material slot, and read the OpenGL/DirectX convention off the normal
map filename.

### Settings

`Settings` at the bottom of the popover (also `Suffixes` in the file browser
sidebar, and the add-on's own preferences) opens the suffix table and the
project roots. Every rule
above is a row there: edit a suffix, point it at a different map, add your own,
or delete one to stop it being recognised. Write the ending without separators —
`basecolor`, `nrm`, `d`. The `+` adds a row, `-` removes the selected one, and
the arrow rebuilds the built-in table. Rules live in the add-on preferences, so
they follow the machine rather than the .blend.

## Compatibility

- Blender 5.1 or newer
- Packaged as a Blender Extension

## Install From Blender Repository

Add the extension repository URL in Blender:

```text
https://mutaform.github.io/qc-maya-viewport/index.json
```

Then sync repositories and search for `QC Maya Viewport`.

## Manual Install

1. Download the release ZIP from GitHub Pages or GitHub Releases.
2. In Blender, open `Edit > Preferences > Extensions`.
3. Use `Install from Disk`.
4. Select `maya_viewport_match.zip`.
5. Enable `QC Maya Viewport`.

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
  origin.py
  preferences.py
  state.py
  texture_loader.py
  ui.py
CHANGELOG.md
tools/
  build_release.ps1
```

## License

This project is licensed under GPL-3.0-or-later, matching the Blender Extension manifest.

