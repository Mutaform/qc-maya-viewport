import bpy

from . import custom_engine
from . import preferences
from .metadata import VERSION_STRING


def draw_view3d_header(self, context):
    row = self.layout.row(align=True)
    row.separator()
    row.operator(
        "mvm.apply_custom",
        text="",
        icon="MATSPHERE",
        depress=custom_engine.is_enabled(),
    )
    row.popover(panel="MVM_PT_custom_shading", text="")


class MVM_PT_custom_shading(bpy.types.Panel):
    bl_label = "QC Maya Viewport"
    bl_idname = "MVM_PT_custom_shading"
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"

    def draw(self, context):
        layout = self.layout
        current = (
            custom_engine.display_mode()
            if custom_engine.is_enabled()
            else "NONE"
        )
        modes = (
            ("NORMAL_ONLY", "Normal Only", "NORMALS_FACE"),
            ("NORMAL_AO", "Normal + AO", "MATERIAL"),
            ("AO_ONLY", "AO Only", "SHADING_TEXTURE"),
            ("ROUGHNESS_ONLY", "Roughness Only", "SHADING_RENDERED"),
            ("DEFAULT_MATERIAL", "Default Material", "MATERIAL"),
        )
        for mode, label, icon in modes:
            operator = layout.operator(
                "mvm.set_custom_mode",
                text=label,
                icon=icon,
                depress=current == mode,
            )
            operator.mode = mode
        layout.separator()
        row = layout.row(align=True)
        row.operator(
            "mvm.load_textures",
            text="Find Textures",
            icon="FILEBROWSER",
        )
        prefs = preferences.get(context)
        if prefs is not None:
            row.prop(prefs, "all_slots", text="")
        layout.operator(
            "mvm.reimport_textures",
            text="Reimport Textures",
            icon="FILE_REFRESH",
        )
        layout.separator()
        layout.label(text=f"ver {VERSION_STRING}")
        layout.separator()
        convention = custom_engine.normal_convention()
        row = layout.row(align=True)
        operator = row.operator(
            "mvm.set_normal_convention",
            text="OpenGL",
            depress=convention == "OPENGL",
        )
        operator.convention = "OPENGL"
        operator = row.operator(
            "mvm.set_normal_convention",
            text="DirectX",
            depress=convention == "DIRECTX",
        )
        operator.convention = "DIRECTX"
        layout.separator()
        layout.operator(
            "mvm.suffix_settings",
            text="Settings",
            icon="PREFERENCES",
        )


CLASSES = (MVM_PT_custom_shading,)
