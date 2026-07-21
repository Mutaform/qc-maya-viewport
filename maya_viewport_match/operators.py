import bpy

from . import custom_engine
from . import state


def _redraw_viewports(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _node_tree_images(node_tree, visited):
    if node_tree is None or node_tree.as_pointer() in visited:
        return set()
    visited.add(node_tree.as_pointer())

    images = set()
    for node in node_tree.nodes:
        image = getattr(node, "image", None)
        if image is not None:
            images.add(image)
        if node.type == "GROUP":
            images.update(_node_tree_images(node.node_tree, visited))
    return images


def _scene_material_images(scene):
    materials = {
        slot.material
        for obj in scene.objects
        for slot in obj.material_slots
        if slot.material is not None and slot.material.use_nodes
    }
    images = set()
    visited = set()
    for material in materials:
        images.update(_node_tree_images(material.node_tree, visited))
    return images


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


CLASSES = (
    MVM_OT_disable_viewer,
    MVM_OT_apply_custom,
    MVM_OT_set_custom_mode,
    MVM_OT_reimport_textures,
)
