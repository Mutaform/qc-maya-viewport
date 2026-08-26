import os

import bpy

from . import custom_engine
from . import origin
from . import preferences
from . import state
from . import texture_loader


def _redraw_viewports(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _scene_node_trees(scene):
    """Every node tree behind the scene's materials, node groups included."""
    trees = []
    visited = set()

    def walk(node_tree):
        if node_tree is None or node_tree.as_pointer() in visited:
            return
        visited.add(node_tree.as_pointer())
        trees.append(node_tree)
        for node in node_tree.nodes:
            if node.type == "GROUP":
                walk(node.node_tree)

    for obj in scene.objects:
        for slot in obj.material_slots:
            material = slot.material
            if material is not None and material.use_nodes:
                walk(material.node_tree)
    return trees


def _scene_material_images(scene):
    images = set()
    for node_tree in _scene_node_trees(scene):
        for node in node_tree.nodes:
            image = getattr(node, "image", None)
            if image is not None:
                images.add(image)
    return images


def _apply_node_convention(scene, convention):
    """Put the same green-channel convention on the Normal Map nodes.

    The viewport shader reads its own setting, but EEVEE and Cycles read the
    node, so both have to move together for the two to agree.
    """
    changed = 0
    for node_tree in _scene_node_trees(scene):
        for node in node_tree.nodes:
            if node.type != "NORMAL_MAP":
                continue
            if not hasattr(node, "convention"):
                return -1
            if node.convention != convention:
                node.convention = convention
                changed += 1
    return changed


class MVM_OT_disable_viewer(bpy.types.Operator):
    bl_idname = "mvm.disable_viewer"
    bl_label = "Disable QC Maya Viewport"

    def execute(self, context):
        custom_engine.disable()
        restored = state.restore(context)
        _redraw_viewports(context)
        if restored:
            self.report({"INFO"}, "Previous Blender viewport restored")
        return {"FINISHED"}


class MVM_OT_apply_custom(bpy.types.Operator):
    bl_idname = "mvm.apply_custom"
    bl_label = "QC Maya Viewport"
    bl_description = "Toggle the QC Maya Viewport GPU renderer"

    def execute(self, context):
        if custom_engine.is_enabled():
            bpy.ops.mvm.disable_viewer()
            self.report({"INFO"}, "QC Maya Viewport disabled")
        else:
            custom_engine.enable(context)
            self.report({"INFO"}, "QC Maya Viewport enabled")
        return {"FINISHED"}


class MVM_OT_set_custom_mode(bpy.types.Operator):
    bl_idname = "mvm.set_custom_mode"
    bl_label = "Set QC Maya Viewport Mode"
    bl_description = "Select a QC Maya Viewport diagnostic shading mode"

    mode: bpy.props.StringProperty()

    def execute(self, context):
        if not custom_engine.is_enabled():
            custom_engine.enable(context)
        custom_engine.set_display_mode(self.mode)
        _redraw_viewports(context)
        return {"FINISHED"}


class MVM_OT_set_normal_convention(bpy.types.Operator):
    bl_idname = "mvm.set_normal_convention"
    bl_label = "Set Normal Map Convention"
    bl_description = (
        "Switch the green-channel convention for normal maps, both in the QC "
        "viewport and on the Normal Map nodes so EEVEE and Cycles agree"
    )
    bl_options = {"REGISTER", "UNDO"}

    convention: bpy.props.StringProperty()

    def execute(self, context):
        custom_engine.set_normal_convention(self.convention)
        changed = _apply_node_convention(context.scene, self.convention)
        _redraw_viewports(context)
        label = {"OPENGL": "OpenGL", "DIRECTX": "DirectX"}.get(
            self.convention, self.convention
        )
        if changed < 0:
            self.report(
                {"WARNING"},
                "QC viewport set to %s; this Blender's Normal Map node has no "
                "convention setting" % label,
            )
        elif changed:
            self.report(
                {"INFO"},
                "%s: QC viewport and %d Normal Map node(s)" % (label, changed),
            )
        else:
            self.report({"INFO"}, "%s: nothing else to change" % label)
        return {"FINISHED"}


class MVM_OT_reimport_textures(bpy.types.Operator):
    bl_idname = "mvm.reimport_textures"
    bl_label = "Reimport Textures"
    bl_description = "Reload all file textures used by materials in this scene"

    def execute(self, context):
        images = _scene_material_images(context.scene)
        reloadable = {
            image for image in images
            if image.source in {"FILE", "SEQUENCE", "MOVIE", "TILED"}
        }
        failed = []
        for image in reloadable:
            try:
                image.reload()
            except RuntimeError as error:
                failed.append((image.name, str(error)))

        _redraw_viewports(context)
        succeeded = len(reloadable) - len(failed)
        skipped = len(images) - len(reloadable)
        if failed:
            names = ", ".join(name for name, _error in failed[:3])
            self.report(
                {"WARNING"},
                f"Reloaded {succeeded} textures; failed: {names}",
            )
        else:
            message = f"Reloaded {succeeded} textures"
            if skipped:
                message += f"; skipped {skipped} generated/viewer images"
            self.report({"INFO"}, message)
        return {"FINISHED"}


def _target_pairs(context, all_slots):
    """The (object, material) pairs one run should fill.

    With the box ticked this covers every material on every selected object,
    so a set that arrives as several one-material meshes takes one press
    instead of one press each.
    """
    obj = context.active_object
    if not all_slots:
        material = getattr(obj, "active_material", None)
        return [(obj, material)] if material is not None else []

    objects = [
        item for item in context.selected_objects
        if item.type == "MESH" and item.material_slots
    ]
    if obj is not None and obj not in objects and obj.material_slots:
        objects.append(obj)

    pairs = []
    seen = set()
    for item in objects:
        for slot in item.material_slots:
            material = slot.material
            if material is None or material.name in seen:
                continue
            seen.add(material.name)
            pairs.append((item, material))
    return pairs


class MVM_OT_load_textures(bpy.types.Operator):
    bl_idname = "mvm.load_textures"
    bl_label = "Find Textures"
    bl_description = (
        "Pick a folder and hook its textures into the active material, "
        "matched by filename suffix and material name"
    )
    bl_options = {"REGISTER", "UNDO"}

    directory: bpy.props.StringProperty(
        subtype="DIR_PATH", options={"SKIP_SAVE"}
    )
    filename: bpy.props.StringProperty(options={"SKIP_SAVE"})
    filter_image: bpy.props.BoolProperty(
        default=True, options={"HIDDEN", "SKIP_SAVE"}
    )
    filter_folder: bpy.props.BoolProperty(
        default=True, options={"HIDDEN", "SKIP_SAVE"}
    )

    recursive: bpy.props.BoolProperty(
        name="Search Subfolders",
        description="Also look inside folders below the selected one",
        default=True,
    )
    match_names: bpy.props.BoolProperty(
        name="Match Material Name",
        description=(
            "Only use files whose name resembles the material. Turn off to "
            "take whatever the folder holds"
        ),
        default=True,
    )
    all_slots: bpy.props.BoolProperty(
        name="All Selected Objects",
        description=(
            "Fill every material on every selected object in one go, instead "
            "of only the active material slot"
        ),
        default=True,
    )
    set_convention: bpy.props.BoolProperty(
        name="Normal Convention From Name",
        description=(
            "Switch the viewport green channel when the normal map filename "
            "says OpenGL or DirectX"
        ),
        default=True,
    )

    @classmethod
    def poll(cls, context):
        if context.active_object is None and not context.selected_objects:
            cls.poll_message_set("Select an object first")
            return False
        objects = list(context.selected_objects)
        if context.active_object is not None:
            objects.append(context.active_object)
        if not any(obj.material_slots for obj in objects):
            cls.poll_message_set("Nothing selected carries a material")
            return False
        return True

    def invoke(self, context, event):
        prefs = preferences.apply(context)
        if prefs is not None:
            # The checkbox next to the button is the setting that sticks.
            self.all_slots = prefs.all_slots
        if not self.directory:
            roots = [root.path for root in prefs.roots] if prefs else []
            origin.clear_cache()
            self.directory = origin.resolve_directory(context, roots)
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text="Texture Search")
        box.prop(self, "recursive")
        box.prop(self, "match_names")
        box.prop(self, "all_slots")
        box.prop(self, "set_convention")
        box.separator()
        box.operator("mvm.suffix_settings", text="Suffixes", icon="PREFERENCES")

    def execute(self, context):
        directory = bpy.path.abspath(self.directory)
        if not directory or not os.path.isdir(directory):
            self.report({"ERROR"}, "Pick a folder that holds the textures")
            return {"CANCELLED"}

        pairs = _target_pairs(context, self.all_slots)
        if not pairs:
            self.report({"ERROR"}, "Nothing selected carries a material")
            return {"CANCELLED"}

        preferences.apply(context)
        entries = texture_loader.scan_folder(directory, self.recursive)
        if not entries:
            self.report(
                {"WARNING"},
                "No files with a known texture suffix in %s"
                % os.path.basename(directory.rstrip("\\/")),
            )
            return {"CANCELLED"}

        convention = None
        total = 0
        filled = 0
        lines = []
        for obj, material in pairs:
            picked, matched, score = texture_loader.resolve(
                entries, material.name, obj.name if obj else "",
                self.match_names,
            )
            if not picked:
                lines.append("%s: no texture matched" % material.name)
                continue
            report = texture_loader.apply_maps(material, picked)
            total += len(report["assigned"])
            filled += 1
            source = "name match" if matched else "folder contents"
            lines.append(
                "%s (%s, score %d): %s" % (
                    material.name, source, int(score),
                    ", ".join(
                        "%s = %s" % (
                            texture_loader.CHANNEL_LABELS.get(channel, channel),
                            name,
                        )
                        for channel, name in sorted(report["assigned"].items())
                    ),
                )
            )
            normal = picked.get(texture_loader.NORMAL)
            if normal is not None:
                convention = texture_loader.normal_convention_from_suffix(
                    normal["suffix"]
                ) or convention

        for line in lines:
            print("[QC Maya Viewport] %s" % line)

        if self.set_convention and convention is not None:
            custom_engine.set_normal_convention(convention)

        _redraw_viewports(context)
        if not total:
            self.report(
                {"WARNING"},
                "Found %d textures but none matched %s"
                % (len(entries), pairs[0][1].name),
            )
            return {"CANCELLED"}

        message = "Linked %d textures into %d of %d material(s)" % (
            total, filled, len(pairs)
        )
        if convention is not None and self.set_convention:
            message += "; normals set to %s" % convention.title()
        self.report({"INFO"}, message + " - see console for details")
        return {"FINISHED"}


CLASSES = (
    MVM_OT_disable_viewer,
    MVM_OT_apply_custom,
    MVM_OT_set_custom_mode,
    MVM_OT_set_normal_convention,
    MVM_OT_reimport_textures,
    MVM_OT_load_textures,
)
