import bpy

from . import camera_sync
from .metadata import VERSION
from .operators import CLASSES as OPERATOR_CLASSES
from .ui import CLASSES as UI_CLASSES
from .ui import draw_view3d_header


bl_info = {
    "name": "QC Maya Viewport",
    "author": "Mutaform Studio",
    "version": VERSION,
    "blender": (5, 1, 0),
    "location": "3D Viewport Header",
    "description": "QC Maya Viewport diagnostic GPU shading",
    "category": "3D View",
}

CLASSES = OPERATOR_CLASSES + UI_CLASSES
LEGACY_CLASSES = (
    "MVM_OT_apply_standard",
    "MVM_OT_enable",
    "MVM_OT_toggle_ao_only",
    "MVM_OT_follow_light",
    "MVM_PT_panel",
)


def _remove_header_callbacks():
    callbacks = bpy.types.VIEW3D_HT_header._dyn_ui_initialize()
    callbacks[:] = [
        callback for callback in callbacks
        if not (
            getattr(callback, "__name__", "") == "draw_view3d_header"
            and "maya_viewport_match" in getattr(callback, "__module__", "")
        )
    ]


def _remove_registered_class(class_name):
    registered = getattr(bpy.types, class_name, None)
    if registered is None:
        return
    try:
        bpy.utils.unregister_class(registered)
    except RuntimeError:
        pass


def register():
    _remove_header_callbacks()
    for class_name in LEGACY_CLASSES:
        _remove_registered_class(class_name)
    for cls in reversed(CLASSES):
        _remove_registered_class(cls.__name__)
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    if hasattr(bpy.types.WindowManager, "mvm_follow_running"):
        del bpy.types.WindowManager.mvm_follow_running
    bpy.types.VIEW3D_HT_header.append(draw_view3d_header)


def unregister():
    _remove_header_callbacks()
    for cls in reversed(CLASSES):
        _remove_registered_class(cls.__name__)
