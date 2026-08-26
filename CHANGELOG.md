# Changelog

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
