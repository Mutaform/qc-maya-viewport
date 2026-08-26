"""Work out which folder on disk an object in the scene came from.

Blender throws the source path away on import, so this does two things: it
records the path of anything imported from now on, and for everything already
in the scene it hunts the asset down by name under the project roots.
"""

import os

import bpy

from . import texture_loader as tl


SOURCE_TAG = "mvm_source"

MODEL_EXTENSIONS = frozenset({
    ".fbx", ".obj", ".ma", ".mb", ".max", ".abc", ".usd", ".usda", ".usdc",
    ".gltf", ".glb", ".dae", ".ztl", ".blend",
})

# Folders never worth walking into while looking for an asset.
SKIPPED_FOLDERS = frozenset({
    "__pycache__", "node_modules", "$recycle.bin",
    "system volume information", "autosave", "backup", "cache",
})

MAX_SEARCH_DEPTH = 4
MAX_TEXTURE_DEPTH = 3
# Only a containment-grade match counts: a stray "body.fbx" must not pass
# for "Elecrtical_boxes01_body".
FOLDER_MATCH_THRESHOLD = 700.0
ASSET_ROOT_THRESHOLD = 700.0

_SEARCH_CACHE = {}
_OBJECT_COUNT = -1


def clear_cache():
    _SEARCH_CACHE.clear()


def _key_tokens(name):
    return tl._strip_prefix(tl._tokens(name))


def _score(target_tokens, name):
    return tl.match_score(target_tokens, _key_tokens(name))


# --------------------------------------------------------------------------
# Recording the path of anything imported from now on
# --------------------------------------------------------------------------

# Importers worth asking about, best guess first.
IMPORTERS = (
    "import_scene.fbx",
    "wm.obj_import",
    "wm.usd_import",
    "wm.alembic_import",
    "wm.stl_import",
    "wm.ply_import",
    "import_scene.gltf",
    "wm.collada_import",
)

_LAST_SEEN = {}


def _importer_paths():
    """The file each importer was last pointed at, this session."""
    paths = {}
    try:
        window_manager = bpy.context.window_manager
    except AttributeError:
        return paths
    for idname in IMPORTERS:
        try:
            props = window_manager.operator_properties_last(idname)
        except (AttributeError, TypeError, RuntimeError):
            continue
        if props is None:
            continue
        path = getattr(props, "filepath", "")
        if not path:
            directory = getattr(props, "directory", "")
            filename = getattr(props, "filename", "")
            path = os.path.join(directory, filename) if directory else ""
        if path and os.path.isfile(bpy.path.abspath(path)):
            paths[idname] = path
    return paths


def last_import_path():
    """The file the import that just ran most likely read.

    Blender keeps no operator history for importers, but it does remember the
    properties each operator was last called with, which is where the path
    comes from. When several importers have been used, the one whose path
    changed since the last look is the one that just ran.
    """
    paths = _importer_paths()
    if not paths:
        return None
    changed = [
        idname for idname, path in paths.items()
        if _LAST_SEEN.get(idname) != path
    ]
    _LAST_SEEN.clear()
    _LAST_SEEN.update(paths)
    for idname in IMPORTERS:
        if idname in changed:
            return paths[idname]
    for idname in IMPORTERS:
        if idname in paths:
            return paths[idname]
    return None


def _last_import_path():
    path = last_import_path()
    if path is None:
        return None
    extension = os.path.splitext(path)[1].lower()
    return path if extension in MODEL_EXTENSIONS else None


@bpy.app.handlers.persistent
def _reset_baseline(*_args):
    """Opening a file replaces every object; take the count afresh."""
    global _OBJECT_COUNT
    _OBJECT_COUNT = -1
    _LAST_SEEN.clear()
    clear_cache()


@bpy.app.handlers.persistent
def _track_new_objects(_scene, _depsgraph):
    """Stamp objects that just appeared with the file they came from."""
    global _OBJECT_COUNT
    count = len(bpy.data.objects)
    if count == _OBJECT_COUNT:
        return
    previous, _OBJECT_COUNT = _OBJECT_COUNT, count
    if previous < 0 or count <= previous:
        return

    path = _last_import_path()
    if path is None:
        return
    for obj in bpy.data.objects:
        if obj.type == "MESH" and SOURCE_TAG not in obj.keys():
            obj[SOURCE_TAG] = path


def register_handler():
    unregister_handler()
    global _OBJECT_COUNT
    # bpy.data is off limits while add-ons register, so let the first
    # depsgraph update take the baseline instead.
    _OBJECT_COUNT = -1
    # Both handlers are persistent: Blender drops the rest on file load, and
    # this one has to survive to keep recording imports.
    bpy.app.handlers.depsgraph_update_post.append(_track_new_objects)
    bpy.app.handlers.load_post.append(_reset_baseline)


def unregister_handler():
    for handlers, name in (
        (bpy.app.handlers.depsgraph_update_post, "_track_new_objects"),
        (bpy.app.handlers.load_post, "_reset_baseline"),
    ):
        handlers[:] = [
            handler for handler in handlers
            if getattr(handler, "__name__", "") != name
        ]


def recorded_folder(obj):
    """The folder of the file this object was imported from, if recorded."""
    if obj is None:
        return ""
    path = obj.get(SOURCE_TAG)
    if not path:
        return ""
    folder = os.path.dirname(bpy.path.abspath(str(path)))
    return folder if os.path.isdir(folder) else ""


# --------------------------------------------------------------------------
# Finding an asset that was imported before any of this existed
# --------------------------------------------------------------------------

def _texture_folder_score(folder, material_tokens):
    """How much this folder looks like the texture folder we want."""
    try:
        names = os.listdir(folder)
    except OSError:
        return 0.0, 0
    images = 0
    best_name = 0.0
    for name in names:
        stem, extension = os.path.splitext(name)
        if extension.lower() not in tl.IMAGE_EXTENSIONS:
            continue
        channel, tokens, _suffix, _packed, _udim = tl.classify(stem)
        if channel is None:
            continue
        images += 1
        if material_tokens:
            best_name = max(
                best_name,
                tl.match_score(material_tokens, tl._strip_prefix(tokens)),
            )
    if not images:
        return 0.0, 0
    return images + best_name, images


def best_texture_folder(asset_root, material_name=""):
    """The subfolder of *asset_root* that actually holds the textures."""
    if not asset_root or not os.path.isdir(asset_root):
        return ""
    material_tokens = _key_tokens(material_name) if material_name else []
    base_depth = asset_root.count(os.sep)
    best = ""
    best_score = 0.0
    for current, folders, _files in os.walk(asset_root):
        if current.count(os.sep) - base_depth >= MAX_TEXTURE_DEPTH:
            folders[:] = []
        folders[:] = [
            folder for folder in folders
            if folder.lower() not in SKIPPED_FOLDERS
            and not folder.startswith(".")
        ]
        score, images = _texture_folder_score(current, material_tokens)
        if images and score > best_score:
            best = current
            best_score = score
    return best


def find_asset_folder(names, roots):
    """Search *roots* for the folder of an asset called any of *names*."""
    if isinstance(names, str):
        names = [names]
    targets = [tokens for tokens in map(_key_tokens, names) if tokens]
    if not targets:
        return ""
    cache_key = (
        tuple("".join(t).lower() for t in targets), tuple(roots)
    )
    if cache_key in _SEARCH_CACHE:
        return _SEARCH_CACHE[cache_key]

    best = ""
    best_score = 0.0
    best_depth = 999
    for root in roots:
        root = os.path.normpath(bpy.path.abspath(root))
        if not os.path.isdir(root):
            continue
        base_depth = root.count(os.sep)
        for current, folders, files in os.walk(root):
            depth = current.count(os.sep) - base_depth
            if depth >= MAX_SEARCH_DEPTH:
                folders[:] = []
            folders[:] = [
                folder for folder in folders
                if folder.lower() not in SKIPPED_FOLDERS
                and not folder.startswith((".", "$"))
            ]
            candidates = []
            if depth:
                candidates.append(os.path.basename(current))
            for name_on_disk in files:
                stem, extension = os.path.splitext(name_on_disk)
                if extension.lower() in MODEL_EXTENSIONS:
                    candidates.append(stem)
            for candidate in candidates:
                score = max(_score(t, candidate) for t in targets)
                # A tie goes to the shallower folder, which is the asset's
                # own directory rather than something nested inside it.
                if score > best_score or (
                    score == best_score and depth < best_depth
                ):
                    best, best_score, best_depth = current, score, depth

    if best_score < FOLDER_MATCH_THRESHOLD:
        best = ""
    else:
        best = _climb_to_asset_root(best, targets[0])
    _SEARCH_CACHE[cache_key] = best
    return best


def _climb_to_asset_root(folder, target):
    """Walk up while a parent still looks like the asset's own folder."""
    best = folder
    current = folder
    for _step in range(3):
        parent = os.path.dirname(current)
        if not parent or parent == current:
            break
        if _score(target, os.path.basename(parent)) >= ASSET_ROOT_THRESHOLD:
            best = parent
        current = parent
    return best


def auto_roots(context):
    """Places worth searching even when the user configured nothing."""
    roots = []

    def add(folder):
        if folder and os.path.isdir(folder) and folder not in roots:
            roots.append(folder)

    for obj in context.scene.objects:
        folder = recorded_folder(obj)
        if folder:
            add(os.path.dirname(folder) or folder)
    for image in bpy.data.images:
        if image.filepath:
            folder = os.path.dirname(bpy.path.abspath(image.filepath))
            add(os.path.dirname(folder) or folder)
    if bpy.data.filepath:
        folder = os.path.dirname(bpy.data.filepath)
        for _step in range(3):
            add(folder)
            parent = os.path.dirname(folder)
            if parent == folder:
                break
            folder = parent
    return roots


def _texture_folder_near(asset_root, material_name=""):
    """The texture folder for this asset, climbing out if it sits deeper."""
    folder = asset_root
    for _step in range(3):
        found = best_texture_folder(folder, material_name)
        if found:
            return found
        parent = os.path.dirname(folder)
        if not parent or parent == folder:
            break
        folder = parent
    return asset_root


def resolve_directory(context, roots=()):
    """Where the Find Textures browser should open for the active object.

    Recorded import path first, then the textures the material already uses,
    then a name search under the project roots, then the .blend folder.
    """
    obj = context.active_object
    material = getattr(obj, "active_material", None)

    recorded = recorded_folder(obj)
    if recorded:
        return _texture_folder_near(
            _climb_to_asset_root(recorded, _key_tokens(obj.name)),
            material.name if material else "",
        )

    if material is not None and material.use_nodes:
        for node in material.node_tree.nodes:
            image = getattr(node, "image", None)
            if image is not None and image.filepath:
                folder = os.path.dirname(bpy.path.abspath(image.filepath))
                if os.path.isdir(folder):
                    return folder

    search_roots = [root for root in roots if root]
    search_roots.extend(auto_roots(context))
    if obj is not None and search_roots:
        names = [obj.name, material.name if material else ""]
        if obj.data is not None:
            names.append(obj.data.name)
        asset = find_asset_folder([name for name in names if name],
                                  search_roots)
        if asset:
            return _texture_folder_near(
                asset, material.name if material else ""
            )

    # Nothing tied to this object worked out. The folder the last import came
    # from still beats opening the browser at nowhere in particular.
    recent = last_import_path()
    if recent:
        folder = os.path.dirname(bpy.path.abspath(recent))
        if os.path.isdir(folder):
            return folder

    if bpy.data.filepath:
        return os.path.dirname(bpy.data.filepath)
    return ""
