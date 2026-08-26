"""Find texture files on disk and wire them into a material."""

import os
import re

import bpy


MAP_TAG = "mvm_map"
AO_CHANNEL_TAG = "mvm_ao_channel"
# Present on an image node whose blue channel is not the normal's Z.
NORMAL_Z_TAG = "mvm_normal_z"
# Which node and channel the Roughness Only viewport mode should read.
ROUGH_CHANNEL_TAG = "mvm_rough_channel"

BASE_COLOR = "BASE_COLOR"
ROUGHNESS = "ROUGHNESS"
METALLIC = "METALLIC"
NORMAL = "NORMAL"
NORMAL_ROUGH = "NORMAL_ROUGH"
AO = "AO"
HEIGHT = "HEIGHT"
EMISSION = "EMISSION"
OPACITY = "OPACITY"
SPECULAR = "SPECULAR"
PACKED = "PACKED"

CHANNEL_LABELS = {
    BASE_COLOR: "Base Color",
    ROUGHNESS: "Roughness",
    METALLIC: "Metallic",
    NORMAL: "Normal",
    NORMAL_ROUGH: "Normal XY + Roughness",
    AO: "AO",
    HEIGHT: "Height",
    EMISSION: "Emission",
    OPACITY: "Opacity",
    SPECULAR: "Specular",
    PACKED: "Packed ORM",
}

# Order used when stacking generated nodes to the left of the shader.
LAYOUT_ORDER = (
    BASE_COLOR, METALLIC, ROUGHNESS, SPECULAR, PACKED,
    EMISSION, OPACITY, AO, HEIGHT, NORMAL, NORMAL_ROUGH,
)

COLOR_CHANNELS = frozenset({BASE_COLOR, EMISSION})

DIRECT_SOCKETS = {
    BASE_COLOR: "Base Color",
    METALLIC: "Metallic",
    ROUGHNESS: "Roughness",
    SPECULAR: "Specular IOR Level",
    EMISSION: "Emission Color",
    OPACITY: "Alpha",
}

IMAGE_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".jpe", ".tga", ".tif", ".tiff", ".exr",
    ".bmp", ".hdr", ".dds", ".webp", ".jp2", ".dpx", ".cin", ".psd",
})

# Working formats Blender reads poorly. Used only when nothing else exists.
LOW_PRIORITY_EXTENSIONS = frozenset({".psd", ".xcf", ".kra", ".dds"})

MAX_DEPTH = 4
MATCH_THRESHOLD = 500.0
MATCH_KEEP_RATIO = 0.6

# Suffix token -> channel. Keys are lowercase with separators removed, so a
# file ending in "_Base_Color", "-basecolor" or ".BaseColor" all hit "basecolor".
SUFFIX_TOKENS = {
    "basecolor": BASE_COLOR, "basecolour": BASE_COLOR, "basecol": BASE_COLOR,
    "basecolormap": BASE_COLOR, "albedo": BASE_COLOR, "alb": BASE_COLOR,
    "diffuse": BASE_COLOR, "diffusemap": BASE_COLOR, "diff": BASE_COLOR,
    "dif": BASE_COLOR, "color": BASE_COLOR, "colour": BASE_COLOR,
    "col": BASE_COLOR, "base": BASE_COLOR, "bc": BASE_COLOR,
    "d": BASE_COLOR, "c": BASE_COLOR,

    "roughness": ROUGHNESS, "roughnessmap": ROUGHNESS, "rough": ROUGHNESS,
    "rgh": ROUGHNESS, "r": ROUGHNESS,

    "metallic": METALLIC, "metalness": METALLIC, "metallness": METALLIC,
    "metal": METALLIC, "metalic": METALLIC, "mtl": METALLIC,
    "met": METALLIC, "m": METALLIC,

    "normal": NORMAL, "normalmap": NORMAL, "normalgl": NORMAL,
    "normalogl": NORMAL, "normalopengl": NORMAL, "normaldx": NORMAL,
    "normaldirectx": NORMAL, "nrmgl": NORMAL, "nrmdx": NORMAL,
    "nor": NORMAL, "norm": NORMAL, "nml": NORMAL, "nm": NORMAL,
    "n": NORMAL,

    # Studio delivery format: R = Normal X, G = Normal Y, B = Roughness.
    "nrm": NORMAL_ROUGH,

    "ambientocclusion": AO, "ambientocclusionmap": AO, "occlusion": AO,
    "ambient": AO, "ao": AO, "occ": AO, "aomap": AO,

    "height": HEIGHT, "heightmap": HEIGHT, "displacement": HEIGHT,
    "disp": HEIGHT, "dsp": HEIGHT, "hgt": HEIGHT, "bump": HEIGHT,
    "bmp": HEIGHT, "h": HEIGHT,

    "emissive": EMISSION, "emission": EMISSION, "emissioncolor": EMISSION,
    "emis": EMISSION, "emit": EMISSION, "glow": EMISSION, "e": EMISSION,

    "opacity": OPACITY, "alpha": OPACITY, "transparency": OPACITY,
    "opac": OPACITY, "mask": OPACITY,

    "specularlevel": SPECULAR, "specularcolor": SPECULAR,
}

# Rule kinds a suffix can carry beyond the plain channels above.
IGNORE = "IGNORE"
PACKED_AUTO = "PACKED_AUTO"
PACKED_PRESETS = {
    "PACKED_MRO": (METALLIC, ROUGHNESS, AO),
    "PACKED_ORM": (AO, ROUGHNESS, METALLIC),
    "PACKED_RMA": (ROUGHNESS, METALLIC, AO),
}

# Suffixes that name a packed map without spelling out the channel letters.
# Studio convention: _spec holds Metalness / Roughness / AO, not a specular
# level, so it is unpacked the same way an _MRO map is.
NAMED_PACKED = {
    "spec": "PACKED_MRO",
    "specular": "PACKED_MRO",
    "specularmap": "PACKED_MRO",
}

# Utility and bake maps that must never be wired into the shader. _cc is a
# tint-mapping mask, the rest are bakes that feed other tools.
IGNORED_SUFFIXES = frozenset({
    "cc", "curve", "curvature", "cavity", "thickness", "objid", "matid",
    "id", "position", "wsn", "worldnormal", "material", "uv", "checker",
    "normalobj", "objnormal", "objectnormal", "normalworld", "worldposition",
})

# Single letter suffixes are ambiguous, so they lose ties to spelled out ones.
WEAK_SUFFIXES = frozenset({"d", "c", "r", "m", "n", "e", "h"})

# Channel packed maps. The letters give the RGB order.
PACKED_LETTERS = {
    "o": AO, "a": AO, "r": ROUGHNESS, "m": METALLIC,
    "h": HEIGHT, "s": SPECULAR, "e": EMISSION,
}
PACKED_NAMES = frozenset({
    "orm", "arm", "rma", "rmo", "mro", "mra",
    "mrao", "rmao", "orma", "ormh", "armh", "mroh",
})

# Tokens that are decoration rather than part of the asset name.
IGNORED_TAIL_TOKENS = frozenset({
    "mixed", "map", "maps", "tex", "texture", "textures", "img",
    "1k", "2k", "4k", "8k", "16k", "512", "1024", "2048", "4096", "8192",
})

# Prefixes studios put in front of asset names (T_, MI_, SM_, ...).
NAME_PREFIXES = frozenset({
    "t", "tex", "texture", "m", "mi", "mat", "mtl", "material",
    "sm", "sk", "st", "ms",
})

DIRECTX_HINTS = ("directx", "dx")
OPENGL_HINTS = ("opengl", "ogl", "gl")


def _tokens(text):
    return [token for token in re.split(r"[^A-Za-z0-9]+", text) if token]


def _strip_prefix(tokens):
    result = list(tokens)
    while len(result) > 1 and result[0].lower() in NAME_PREFIXES:
        result.pop(0)
    return result


def _is_udim(token):
    return len(token) == 4 and token.isdigit() and 1001 <= int(token) <= 1999


def _strip_tail(tokens):
    result = list(tokens)
    udim = None
    while result:
        tail = result[-1].lower()
        if _is_udim(tail):
            udim = int(tail)
            result.pop()
            continue
        if tail in IGNORED_TAIL_TOKENS:
            result.pop()
            continue
        break
    return result, udim


def _packed_order(key):
    if key not in PACKED_NAMES:
        return None
    order = []
    for letter in key:
        channel = PACKED_LETTERS.get(letter)
        if channel is None or channel in order:
            return None
        order.append(channel)
    return tuple(order)


# The user's editable table, filled from the add-on preferences before a run.
# While it holds anything it is the only source of truth, so a rule the user
# deleted really is gone.
RULES = {}


def set_rules(mapping):
    """Replace the suffix table with the user's own (empty = built-in)."""
    RULES.clear()
    RULES.update(mapping or {})


def default_rules():
    """The built-in table as (suffix, kind) pairs, for seeding preferences."""
    rules = {suffix: channel for suffix, channel in SUFFIX_TOKENS.items()}
    rules.update(NAMED_PACKED)
    rules.update({suffix: PACKED_AUTO for suffix in PACKED_NAMES})
    rules.update({suffix: IGNORE for suffix in IGNORED_SUFFIXES})
    return sorted(rules.items())


def _kind_for(suffix):
    if RULES:
        return RULES.get(suffix)
    if suffix in IGNORED_SUFFIXES:
        return IGNORE
    kind = NAMED_PACKED.get(suffix)
    if kind is not None:
        return kind
    if suffix in PACKED_NAMES:
        return PACKED_AUTO
    return SUFFIX_TOKENS.get(suffix)


def _resolve_kind(kind, suffix):
    """Turn a rule kind into (channel, packed order). Channel None = ignore."""
    if kind == IGNORE:
        return None, None
    if kind == PACKED_AUTO:
        return PACKED, _packed_order(suffix) or PACKED_PRESETS["PACKED_ORM"]
    order = PACKED_PRESETS.get(kind)
    if order is not None:
        return PACKED, order
    return kind, None


def classify(stem):
    """Split a file stem into (channel, name tokens, suffix, packed, udim)."""
    tokens = _tokens(stem)
    udim = None
    # A UDIM number trails the suffix ("Body_basecolor.1001"), so it has to
    # come off before the suffix can be recognised.
    while tokens and _is_udim(tokens[-1]):
        udim = int(tokens.pop())
    if not tokens:
        return None, [], "", None, udim
    for size in (3, 2, 1):
        if size > len(tokens):
            continue
        suffix = "".join(tokens[-size:]).lower()
        kind = _kind_for(suffix)
        if kind is None:
            continue
        channel, packed = _resolve_kind(kind, suffix)
        if channel is None:
            return None, tokens, suffix, None, udim
        return channel, tokens[:-size], suffix, packed, udim
    return None, tokens, "", None, udim


def normal_convention_from_suffix(suffix):
    """Read an explicit OpenGL/DirectX tag off a normal map suffix."""
    for hint in DIRECTX_HINTS:
        if suffix.endswith(hint):
            return "DIRECTX"
    for hint in OPENGL_HINTS:
        if suffix.endswith(hint):
            return "OPENGL"
    return None


def match_score(target_tokens, candidate_tokens):
    """Rough name similarity, 0 (nothing in common) to 1000 (identical)."""
    if not target_tokens or not candidate_tokens:
        return 0.0
    target = "".join(target_tokens).lower()
    candidate = "".join(candidate_tokens).lower()
    if target == candidate:
        return 1000.0
    if target in candidate or candidate in target:
        ratio = min(len(target), len(candidate)) / float(
            max(len(target), len(candidate))
        )
        return 600.0 + 300.0 * ratio
    remaining = [token.lower() for token in candidate_tokens]
    common = 0
    for token in target_tokens:
        token = token.lower()
        if token in remaining:
            remaining.remove(token)
            common += 1
    if not common:
        return 0.0
    span = float(max(len(target_tokens), len(candidate_tokens)))
    return 500.0 * (common / span)


def _entry(path, name, stem, channel, tokens, suffix, packed, udim, depth):
    extension = os.path.splitext(name)[1].lower()
    return {
        "path": path,
        "name": name,
        "stem": stem,
        "channel": channel,
        "packed": packed,
        "suffix": suffix,
        "tokens": _strip_prefix(tokens),
        "udim": udim,
        "depth": depth,
        # One letter says very little, so those lose ties to spelled out
        # suffixes. Covers rules the user adds later, too.
        "weak": len(suffix) <= 1,
        "low_format": extension in LOW_PRIORITY_EXTENSIONS,
    }


def scan_folder(directory, recursive=True):
    """Return every classifiable texture file under *directory*."""
    found = []
    bare = []
    # The file browser hands over a trailing separator; without normalising it
    # os.walk's folder string stops matching os.path.dirname of the files.
    directory = os.path.normpath(directory)
    root_depth = directory.count(os.sep)
    for current, folders, files in os.walk(directory):
        depth = current.count(os.sep) - root_depth
        if not recursive:
            folders[:] = []
        elif depth >= MAX_DEPTH:
            folders[:] = []
        for name in files:
            stem, extension = os.path.splitext(name)
            if extension.lower() not in IMAGE_EXTENSIONS:
                continue
            channel, tokens, suffix, packed, udim = classify(stem)
            tokens, trailing_udim = _strip_tail(tokens)
            udim = udim if udim is not None else trailing_udim
            path = os.path.join(current, name)
            if channel is None:
                # A recognised-but-ignored suffix (_cc and friends) is not a
                # nameless file, so it never gets promoted to base color.
                if not suffix:
                    bare.append((
                        path, name, stem, tokens, udim, depth,
                        os.path.dirname(path),
                    ))
                continue
            found.append(_entry(
                path, name, stem, channel, tokens, suffix, packed, udim, depth
            ))

    # A file with no suffix at all is the base color of its set, as long as a
    # suffixed sibling with the very same name sits next to it
    # (Voron_..._cabin.tga beside Voron_..._cabin_nm.tga).
    families = {
        (os.path.dirname(entry["path"]).lower(),
         "".join(entry["tokens"]).lower())
        for entry in found
    }
    for path, name, stem, tokens, udim, depth, folder in bare:
        key = (folder.lower(), "".join(_strip_prefix(tokens)).lower())
        if key in families:
            found.append(_entry(
                path, name, stem, BASE_COLOR, tokens, "", None, udim, depth
            ))
    return found


def _collapse_udim(entries):
    """Group the UDIM tiles of one map into a single entry with a tile list."""
    groups = {}
    for entry in entries:
        key = (
            entry["channel"],
            "".join(entry["tokens"]).lower(),
            entry["suffix"],
            os.path.dirname(entry["path"]).lower(),
            os.path.splitext(entry["path"])[1].lower(),
        )
        groups.setdefault(key, []).append(entry)

    collapsed = []
    for members in groups.values():
        tiles = sorted(
            member["udim"] for member in members if member["udim"] is not None
        )
        if len(members) == 1 or len(tiles) != len(members):
            collapsed.extend(members)
            continue
        members.sort(key=lambda member: member["udim"])
        first = dict(members[0])
        first["tiles"] = tiles
        collapsed.append(first)
    return collapsed


def resolve(entries, material_name, object_name="", match_names=True):
    """Pick the best file per channel for *material_name*.

    Returns ``(picked, matched, best_score)``. When no file resembles the
    material name, every file stays in the running so a folder holding a
    single texture set still gets assigned.
    """
    entries = _collapse_udim(entries)
    if not entries:
        return {}, False, 0.0

    material_tokens = _strip_prefix(_tokens(material_name))
    object_tokens = _strip_prefix(_tokens(object_name))
    scores = {}
    for index, entry in enumerate(entries):
        score = match_score(material_tokens, entry["tokens"])
        if object_tokens:
            score = max(score, 0.9 * match_score(object_tokens, entry["tokens"]))
        scores[index] = score

    best = max(scores.values())
    matched = match_names and best >= MATCH_THRESHOLD
    if matched:
        cutoff = max(MATCH_THRESHOLD, best * MATCH_KEEP_RATIO)
        candidates = [
            (index, entry) for index, entry in enumerate(entries)
            if scores[index] >= cutoff
        ]
    else:
        candidates = list(enumerate(entries))

    picked = {}
    for index, entry in candidates:
        rank = (
            scores[index],
            0 if entry.get("low_format") else 1,
            -entry.get("depth", 0),
            0 if entry["weak"] else 1,
            -len(entry["name"]),
        )
        current = picked.get(entry["channel"])
        if current is None or rank > current[0]:
            picked[entry["channel"]] = (rank, entry)
    return (
        {channel: entry for channel, (_rank, entry) in picked.items()},
        matched,
        best,
    )


def _set_colorspace(image, name):
    try:
        if image.colorspace_settings.name != name:
            image.colorspace_settings.name = name
    except (TypeError, AttributeError):
        pass


def _load_image(entry, data_map):
    image = bpy.data.images.load(entry["path"], check_existing=True)
    tiles = entry.get("tiles")
    if tiles and len(tiles) > 1 and tiles[0] == 1001 and image.source != "TILED":
        try:
            image.source = "TILED"
            existing = {tile.number for tile in image.tiles}
            for number in tiles[1:]:
                if number not in existing:
                    image.tiles.new(tile_number=number)
        except (RuntimeError, TypeError):
            image.source = "FILE"
    _set_colorspace(image, "Non-Color" if data_map else "sRGB")
    if data_map and image.alpha_mode == "STRAIGHT":
        image.alpha_mode = "CHANNEL_PACKED"
    return image


def _active_output(node_tree):
    fallback = None
    for node in node_tree.nodes:
        if node.type != "OUTPUT_MATERIAL":
            continue
        if node.is_active_output:
            return node
        fallback = node
    return fallback


def ensure_principled(material):
    """Return the Principled BSDF of *material*, creating one if needed."""
    material.use_nodes = True
    node_tree = material.node_tree
    output = _active_output(node_tree)
    if output is not None:
        surface = output.inputs.get("Surface")
        if surface is not None and surface.is_linked:
            source = surface.links[0].from_node
            if source.type == "BSDF_PRINCIPLED":
                return source
    for node in node_tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            return node
    shader = node_tree.nodes.new("ShaderNodeBsdfPrincipled")
    shader.location = (0.0, 300.0)
    if output is None:
        output = node_tree.nodes.new("ShaderNodeOutputMaterial")
        output.location = (320.0, 300.0)
    node_tree.links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    return shader


def _tagged_node(node_tree, channel):
    for node in node_tree.nodes:
        if node.type == "TEX_IMAGE" and node.get(MAP_TAG) == channel:
            return node
    return None


def _classified_node(node_tree, channel):
    """An untagged image node whose filename already reads as *channel*.

    This is what lets a rerun repoint an existing (often broken) node at the
    file it was always meant to hold, instead of piling a duplicate next to it.
    """
    for node in node_tree.nodes:
        if node.type != "TEX_IMAGE" or node.image is None:
            continue
        if node.get(MAP_TAG) is not None:
            continue
        # bpy.path.basename copes with Blender's "//" relative prefix, which
        # os.path.basename reads as a UNC root and returns empty for.
        source = bpy.path.basename(node.image.filepath) or node.image.name
        stem = os.path.splitext(source)[0]
        if classify(stem)[0] == channel:
            return node
    return None


def _linked_image_node(socket, channel):
    """Walk back from *socket* through helper nodes to an image node."""
    visited = set()
    stack = [socket]
    while stack:
        current = stack.pop()
        if current is None or not current.is_linked:
            continue
        node = current.links[0].from_node
        if node.as_pointer() in visited:
            continue
        visited.add(node.as_pointer())
        if node.type == "TEX_IMAGE":
            # Never steal a node that is already spoken for.
            tag = node.get(MAP_TAG)
            return None if tag is not None and tag != channel else node
        if node.type in {
            "NORMAL_MAP", "BUMP", "SEPARATE_COLOR", "SEPRGB", "GROUP",
        }:
            stack.extend(node.inputs)
    return None


def _helper_node(node_tree, socket, node_type, bl_idname, tag):
    for node in node_tree.nodes:
        if node.type == node_type and node.get(MAP_TAG) == tag:
            return node, False
    if socket is not None and socket.is_linked:
        source = socket.links[0].from_node
        if source.type == node_type:
            source[MAP_TAG] = tag
            return source, False
    node = node_tree.nodes.new(bl_idname)
    node[MAP_TAG] = tag
    return node, True


class _Builder(object):
    """Creates or reuses the image nodes needed for one material."""

    def __init__(self, material, shader):
        self.material = material
        self.tree = material.node_tree
        self.shader = shader
        self.column_x = shader.location.x - 900.0
        self.next_y = shader.location.y + 320.0
        self.created = 0

    def place(self, node, x_offset=0.0, y=None):
        node.location = (
            self.column_x + x_offset,
            self.next_y if y is None else y,
        )

    def image_node(self, channel, socket_name=None):
        node = _tagged_node(self.tree, channel)
        if node is None:
            node = _classified_node(self.tree, channel)
        if node is None and socket_name:
            node = _linked_image_node(
                self.shader.inputs.get(socket_name), channel
            )
        if node is None:
            node = self.tree.nodes.new("ShaderNodeTexImage")
            node.width = 260.0
            self.place(node)
            self.created += 1
        self.next_y -= 300.0
        node[MAP_TAG] = channel
        node.label = CHANNEL_LABELS.get(channel, channel)
        return node

    def connect(self, output_socket, socket_name):
        target = self.shader.inputs.get(socket_name)
        if target is None:
            return False
        self.tree.links.new(output_socket, target)
        return True


NRM_GROUP_NAME = "MVM Unpack NRM"


def _math(nodes, operation, x, values, *defaults):
    node = nodes.new("ShaderNodeMath")
    node.operation = operation
    node.location = (x, values)
    for index, value in enumerate(defaults):
        if value is not None:
            node.inputs[index].default_value = value
    return node


def _nrm_group():
    """Node group that turns an _NRM map into a normal colour + roughness.

    R and G hold the normal's X and Y, B holds roughness, so Z has to be
    rebuilt: z = sqrt(1 - x^2 - y^2), then re-encoded to 0..1 for the Normal
    Map node. Blender's SQRT returns 0 for negative input, which is the clamp
    this needs.
    """
    group = bpy.data.node_groups.get(NRM_GROUP_NAME)
    if group is not None and group.bl_idname == "ShaderNodeTree":
        return group

    group = bpy.data.node_groups.new(NRM_GROUP_NAME, "ShaderNodeTree")
    group.interface.new_socket(
        "Color", in_out="INPUT", socket_type="NodeSocketColor"
    )
    group.interface.new_socket(
        "Normal Color", in_out="OUTPUT", socket_type="NodeSocketColor"
    )
    group.interface.new_socket(
        "Roughness", in_out="OUTPUT", socket_type="NodeSocketFloat"
    )
    nodes = group.nodes
    links = group.links

    group_in = nodes.new("NodeGroupInput")
    group_in.location = (-800.0, 0.0)
    group_out = nodes.new("NodeGroupOutput")
    group_out.location = (600.0, 0.0)
    separate = nodes.new("ShaderNodeSeparateColor")
    separate.location = (-600.0, 0.0)
    links.new(group_in.outputs["Color"], separate.inputs["Color"])

    x = _math(nodes, "MULTIPLY_ADD", -400.0, 200.0, None, 2.0, -1.0)
    y = _math(nodes, "MULTIPLY_ADD", -400.0, 20.0, None, 2.0, -1.0)
    links.new(separate.outputs["Red"], x.inputs[0])
    links.new(separate.outputs["Green"], y.inputs[0])

    x2 = _math(nodes, "MULTIPLY", -220.0, 200.0)
    y2 = _math(nodes, "MULTIPLY", -220.0, 20.0)
    links.new(x.outputs["Value"], x2.inputs[0])
    links.new(x.outputs["Value"], x2.inputs[1])
    links.new(y.outputs["Value"], y2.inputs[0])
    links.new(y.outputs["Value"], y2.inputs[1])

    total = _math(nodes, "ADD", -40.0, 120.0)
    links.new(x2.outputs["Value"], total.inputs[0])
    links.new(y2.outputs["Value"], total.inputs[1])

    rest = _math(nodes, "SUBTRACT", 120.0, 120.0, 1.0)
    links.new(total.outputs["Value"], rest.inputs[1])

    z = _math(nodes, "SQRT", 280.0, 120.0)
    links.new(rest.outputs["Value"], z.inputs[0])

    encoded = _math(nodes, "MULTIPLY_ADD", 280.0, -60.0, None, 0.5, 0.5)
    links.new(z.outputs["Value"], encoded.inputs[0])

    combine = nodes.new("ShaderNodeCombineColor")
    combine.location = (440.0, 60.0)
    links.new(separate.outputs["Red"], combine.inputs["Red"])
    links.new(separate.outputs["Green"], combine.inputs["Green"])
    links.new(encoded.outputs["Value"], combine.inputs["Blue"])

    links.new(combine.outputs["Color"], group_out.inputs["Normal Color"])
    links.new(separate.outputs["Blue"], group_out.inputs["Roughness"])
    return group


def _clear_tag(node_tree, tag):
    for node in node_tree.nodes:
        if tag in node.keys():
            del node[tag]


def _clear_ao_tags(node_tree):
    _clear_tag(node_tree, AO_CHANNEL_TAG)


def _build_normal_chain(builder, assigned):
    """Wire the normal map, and the height map on top of it, into Normal."""
    tree = builder.tree
    normal_socket = builder.shader.inputs.get("Normal")
    normal_output = None

    color_source = None
    normal_item = assigned.get(NORMAL)
    nrm_item = assigned.get(NORMAL_ROUGH)
    if normal_item is not None:
        color_source = normal_item[0].outputs["Color"]
    if nrm_item is not None:
        unpack, created = _helper_node(
            tree, normal_socket, "GROUP", "ShaderNodeGroup", NORMAL_ROUGH
        )
        if created or unpack.node_tree is None:
            unpack.node_tree = _nrm_group()
            builder.place(unpack, 320.0, nrm_item[0].location.y)
        tree.links.new(nrm_item[0].outputs["Color"], unpack.inputs["Color"])
        if color_source is None:
            color_source = unpack.outputs["Normal Color"]
        if ROUGHNESS not in assigned:
            builder.connect(unpack.outputs["Roughness"], "Roughness")

    if color_source is not None:
        normal_map, created = _helper_node(
            tree, normal_socket, "NORMAL_MAP", "ShaderNodeNormalMap", NORMAL
        )
        if created:
            builder.place(
                normal_map, 620.0,
                (normal_item or nrm_item)[0].location.y,
            )
        tree.links.new(color_source, normal_map.inputs["Color"])
        # Blender 5.x carries the green-channel convention on the node itself,
        # so a filename that spells it out can set it here too.
        convention = normal_convention_from_suffix(
            (normal_item or nrm_item)[1]["suffix"]
        )
        if convention is not None and hasattr(normal_map, "convention"):
            normal_map.convention = convention
        normal_output = normal_map.outputs["Normal"]

    height_item = assigned.get(HEIGHT)
    if height_item is not None:
        bump, created = _helper_node(
            tree, normal_socket, "BUMP", "ShaderNodeBump", HEIGHT
        )
        if created:
            builder.place(bump, 780.0, height_item[0].location.y)
            bump.inputs["Strength"].default_value = 0.2
        tree.links.new(height_item[0].outputs["Color"], bump.inputs["Height"])
        if normal_output is not None:
            tree.links.new(normal_output, bump.inputs["Normal"])
        normal_output = bump.outputs["Normal"]

    if normal_output is not None:
        builder.connect(normal_output, "Normal")


def _build_packed(builder, assigned):
    """Split an ORM style map. Returns the (AO, roughness) sources."""
    packed_item = assigned.get(PACKED)
    if packed_item is None:
        return None, None

    tree = builder.tree
    separate, created = _helper_node(
        tree, None, "SEPARATE_COLOR", "ShaderNodeSeparateColor", PACKED
    )
    if created:
        builder.place(separate, 320.0, packed_item[0].location.y)
    tree.links.new(packed_item[0].outputs["Color"], separate.inputs["Color"])

    ao_source = None
    rough_source = None
    for index, channel in enumerate(packed_item[1]["packed"] or ()):
        if channel in assigned:
            continue
        if channel == AO:
            ao_source = (packed_item[0], index)
            continue
        if channel == ROUGHNESS:
            rough_source = (packed_item[0], index)
        socket_name = DIRECT_SOCKETS.get(channel)
        if socket_name:
            builder.connect(separate.outputs[index], socket_name)
    return ao_source, rough_source


def prune_packed(picked):
    """Drop a packed map whose every channel already has a dedicated file."""
    if NORMAL_ROUGH in picked and NORMAL in picked and ROUGHNESS in picked:
        del picked[NORMAL_ROUGH]
    packed = picked.get(PACKED)
    if packed is not None:
        order = packed.get("packed") or ()
        if order and all(channel in picked for channel in order):
            del picked[PACKED]
    return picked


def apply_maps(material, picked):
    """Wire the picked files into *material*. Returns a report dict."""
    picked = prune_packed(dict(picked))
    shader = ensure_principled(material)
    builder = _Builder(material, shader)
    tree = material.node_tree
    _clear_ao_tags(tree)
    _clear_tag(tree, NORMAL_Z_TAG)
    _clear_tag(tree, ROUGH_CHANNEL_TAG)

    assigned = {}
    for channel in LAYOUT_ORDER:
        entry = picked.get(channel)
        if entry is None:
            continue
        node = builder.image_node(channel, DIRECT_SOCKETS.get(channel))
        node.image = _load_image(entry, channel not in COLOR_CHANNELS)
        assigned[channel] = (node, entry)

    base_item = assigned.get(BASE_COLOR)
    opacity_item = assigned.get(OPACITY)
    if opacity_item is not None:
        if base_item is not None \
                and opacity_item[1]["path"] == base_item[1]["path"]:
            # Alpha lives in the base color file, no second node needed.
            tree.nodes.remove(opacity_item[0])
            del assigned[OPACITY]
            builder.connect(base_item[0].outputs["Alpha"], "Alpha")
        if hasattr(material, "surface_render_method"):
            material.surface_render_method = "DITHERED"

    for channel, socket_name in DIRECT_SOCKETS.items():
        item = assigned.get(channel)
        if item is not None:
            builder.connect(item[0].outputs["Color"], socket_name)

    if EMISSION in assigned:
        strength = shader.inputs.get("Emission Strength")
        if strength is not None and strength.default_value <= 0.0:
            strength.default_value = 1.0

    _build_normal_chain(builder, assigned)
    ao_source, rough_source = _build_packed(builder, assigned)

    rough_item = assigned.get(ROUGHNESS)
    if rough_item is not None:
        rough_source = (rough_item[0], -1)
    elif NORMAL_ROUGH in assigned:
        # _NRM keeps roughness in blue.
        rough_source = (assigned[NORMAL_ROUGH][0], 2)
    if rough_source is not None:
        rough_source[0][ROUGH_CHANNEL_TAG] = rough_source[1]

    ao_item = assigned.get(AO)
    if ao_item is not None:
        ao_source = (ao_item[0], -1)
    if ao_source is not None:
        ao_source[0][AO_CHANNEL_TAG] = ao_source[1]

    # Nothing to put in the diffuse but an AO map exists: use it, the way the
    # studio's older scenes already do.
    ao_to_base = base_item is None and ao_item is not None
    if ao_to_base:
        builder.connect(ao_item[0].outputs["Color"], "Base Color")

    nrm_item = assigned.get(NORMAL_ROUGH)
    if nrm_item is not None and NORMAL not in assigned:
        nrm_item[0][NORMAL_Z_TAG] = 1

    return {
        "assigned": {
            channel: entry["name"]
            for channel, (_node, entry) in assigned.items()
        },
        "created_nodes": builder.created,
        "ao_packed": ao_item is None and ao_source is not None,
        "ao_to_base": ao_to_base,
    }


def initial_directory(context):
    """Best guess for where the file browser should open."""
    material = getattr(context.active_object, "active_material", None)
    if material is not None and material.use_nodes:
        for node in material.node_tree.nodes:
            image = getattr(node, "image", None)
            if image is not None and image.filepath:
                folder = os.path.dirname(bpy.path.abspath(image.filepath))
                if os.path.isdir(folder):
                    return folder
    if bpy.data.filepath:
        return os.path.dirname(bpy.data.filepath)
    for image in bpy.data.images:
        if image.filepath:
            folder = os.path.dirname(bpy.path.abspath(image.filepath))
            if os.path.isdir(folder):
                return folder
    return ""
