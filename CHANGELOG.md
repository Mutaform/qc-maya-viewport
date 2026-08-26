# Changelog

## 0.34.1

- Put the key light's upward tilt back. 0.34.0 aimed it straight down the
  view axis on the strength of a flat-plane reading, but a plane cannot show
  where a light is. A shaded sphere can: Maya's puts its brightest point 15%
  of the radius above centre, so the light is tilted. Flattening it made the
  shading read as if lit from the wrong side.
- Specular back to 0.30, which is what the tilt needs to reach Maya's peak.

Known difference: Maya's blinn highlight is tighter and peaks about 12/255
above its surrounding surface, this shader's Blinn-Phong lobe about 5. The
lobe shape differs, not the level.

## 0.34.0

- **Maya's view transform is reproduced, so the whole grey ramp matches, not
  just one point.** 0.33.0 matched the mid grey by lowering the diffuse
  level, but Maya runs its viewport through a tone curve (ACES 1.0 SDR-video
  by default) and no single multiplier can follow that. The curve was
  measured out of Maya - a surfaceShader stepped through 16 known values,
  read back off a playblast - and fitted into the shader. Worst error is
  under 1/255 above black.
- With the curve in place the levels are Maya's own again: diffuse 0.4
  (blinn colour 0.5 x diffuse 0.8) and a 0.22 highlight.
- **The key light points straight down the view axis**, like Maya's default
  headlight. It used to be tilted 0.25 up, which shifted the shading gradient
  across every surface.
- A flat plane facing the camera now reads 148/255 unlit-side and 179/255 at
  the highlight, against Maya's 146 and 179.
- `Settings` gained a `Maya Tone Curve` switch beside the two levels, for a
  Maya set to plain sRGB rather than ACES.

## 0.33.0

- **The viewport greys now match Maya.** The shading levels were guesses;
  they are measured now. A flat plane facing the camera, shaded by a default
  blinn (colour 0.5, diffuse 0.8) under the default headlight, reads 146/255
  in Maya 2025 and 179/255 with the highlight. The QC viewport was painting
  183 and 187 - visibly lighter. Diffuse went 0.5 -> 0.304 and specular
  0.3 -> 0.23, which lands on 145 and 180.
- Both levels are exposed in `Settings` under `Maya Match`. The calibration
  assumes Maya's default ACES 1.0 SDR-video view transform; a Maya set to
  plain sRGB wants roughly 0.4 diffuse instead.

## 0.32.0

- **Checkbox next to `Find Textures`, on by default.** One press now fills
  every material on every selected object, so a set that arrives as twenty
  one-material meshes takes one press instead of one per material. Untick it
  to go back to filling only the active slot. The state is remembered.
- Fixed: files named per UDIM tile (`bake_1001_ao`, `bake_1002_ao`) were
  merged into a single tiled image, so every material got tile 1001. When the
  material name carries the tile number (`vzor_1002`), the files are treated
  as separate sets and each material takes its own.

## 0.31.0

- **Fixed: Find Textures did not open on the imported mesh's folder.** Two
  things were wrong. The import tracker read the path off the operator
  history, but Blender never puts importers there; it now asks the window
  manager for the properties each importer was last called with, which does
  hold the path. And the handler was not marked persistent, so Blender threw
  it away the moment a .blend was opened.
- When an object carries no recorded path and the name search finds nothing,
  the browser falls back to the folder of the last import rather than opening
  nowhere. That covers everything imported before this version.

## 0.30.4

- **Fixed the viewport going black on part of the scene.** `Roughness Only`
  added five push constants to the shader, which shifted the `MAT3`
  normalMatrix inside the constant block and fed the vertex stage garbage
  object normals - whole objects rendered black in every mode, `Default
  Material` included. normalMatrix is a `MAT4` now, where the padding is
  unambiguous.
- Every texture is built before any sampler is assigned. Creating one in
  between disturbed the slots already bound.
- An image whose file is missing falls back to flat shading instead of being
  handed to the GPU as a black texture.

## 0.30.1

- Reverted 0.30.0. The header dropdown is a panel popover again: turning it
  into a menu did left-align the labels, but it looked and behaved worse.
  Blender centres button labels in a popover and there is no setting for it.

## 0.29.1

- Turning the viewer on now reads the green-channel convention off the scene's
  Normal Map nodes. The viewport setting is a module global, so it used to
  reset to OpenGL whenever the add-on reloaded while the nodes stayed on
  DirectX, and the two silently disagreed.

## 0.29.0

- **`OpenGL` / `DirectX` now switch the Normal Map nodes as well**, so the
  regular EEVEE and Cycles render agrees with the QC viewport instead of only
  the viewport changing. Every Normal Map node behind the scene's materials
  moves together, node groups included, and the change is undoable.

## 0.28.1

- Fixed a crash in `Find Textures` on any material without a packed map:
  the packed-map builder returned one value where two were expected, so a set
  of plain `_ao` + `_normal` files raised
  `TypeError: cannot unpack non-iterable NoneType object`. The material was
  left half wired; running `Find Textures` again finishes it.

## 0.28.0

- **Find Textures now opens on the object's own asset folder**, not a generic
  browser. Blender throws the import path away, so this works two ways: the
  path of anything imported from now on is recorded on the object, and for
  everything already in the scene the asset is found by name under the
  project roots you set in `Settings`. A hit inside a `Meshes` subfolder
  climbs out to the folder that really holds the maps.
- Object-space bakes (`_normalobj`, `_objnormal`, `_normalworld`,
  `_worldposition`) are ignored like the other utility maps.

## 0.27.0

- **New viewport mode `Roughness Only`**, in the popover right after `AO Only`.
  Shows the roughness map flat, pulling the right channel out of a packed
  `_ORM`/`_MRO`/`_spec` map or out of the blue of an `_NRM` map. A material with
  no roughness reads as mid grey rather than white.

## 0.26.1

- Every edit to the suffix table now flags the preferences as changed.
  Without it, rows added or removed with the `+`/`-` buttons could be dropped
  on exit by Auto-Save Preferences.
- The settings dialog says whether the table is being saved, and offers a
  `Save Preferences` button when auto-save is off.

## 0.26.0

- **New `Settings` entry at the bottom of the popover**: the whole suffix table
  is now editable. Change what a suffix maps to, add your own, or delete one to
  stop it being recognised. Seeded with 104 built-in rules, with a reset button.
- Also reachable as `Suffixes` in the Find Textures sidebar and from the
  add-on's own preferences. Rules are stored in the Blender preferences, so they
  survive a restart and apply to every scene on the machine.

## 0.25.1

- **Fixed: the viewport could get stuck on permanently.** The GPU draw handle
  lived only in a module variable, so reloading or disabling the add-on while
  the viewer ran orphaned the handler — it kept drawing with nothing left able
  to switch it off. The handle is now kept where a reload cannot lose it,
  stale handlers are swept on register, and disabling the add-on shuts the
  viewer down.

## 0.25.0

- `_spec` is read as a packed **Metalness / Roughness / AO** map, matching the
  studio's own deliveries, instead of a specular level.
- `_cc` (tint-mapping mask) and the bake maps `_curve`, `_cavity`,
  `_thickness`, `_objid`, `_matid`, `_position`, `_id` are never wired up.
- Fixed: a folder picked in the file browser arrives with a trailing separator,
  which stopped the "file with no suffix is the base color" rule from firing.

## 0.24.0

- **`_NRM` support** — the delivery format where R and G hold the normal and B
  holds roughness. Unpacked through a `MVM Unpack NRM` node group that rebuilds
  Z as `sqrt(1 - x² - y²)`; the QC viewport rebuilds the same Z on the GPU.
  A plain `_Normal` plus `_Roughness` in the same folder still win.
- Recognises `_COL` and `_NM`.
- A file with **no suffix at all** is taken as the base color when a suffixed
  sibling with the same name sits next to it.
- When a set has an `_AO` map but nothing for the diffuse, AO goes to Base Color.
- A file in the chosen folder beats the same file in a subfolder, so full-size
  maps win over a `1k/` copy.
- A filename that spells out OpenGL or DirectX now also sets the Normal Map
  node's convention, not just the viewport's.

## 0.23.0

- **New: `Find Textures`.** Select an object and a material slot, pick the
  folder holding the maps, and the textures are linked into the Principled BSDF
  by their filename suffix. Data maps get `Non-Color`, normals go through a
  Normal Map node, height through a Bump node, and packed `_ORM`-style maps are
  split into their channels.
- When several texture sets share one folder, the set whose name matches the
  material is used; with no match, whatever the folder holds is assigned.
- Existing textures in a material are repointed rather than duplicated, and
  `.psd` files only win when nothing else carries the same map.
- Options: search subfolders, match material name, fill every material slot,
  read the normal convention off the filename.

## 0.22.8 and earlier

Diagnostic GPU viewport: `Normal Only`, `Normal + AO`, `AO Only`,
`Default Material`, OpenGL/DirectX normal convention, `Reimport Textures`.
