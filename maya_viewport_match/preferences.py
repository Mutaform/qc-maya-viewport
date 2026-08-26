"""User editable table of texture filename suffixes."""

import bpy

from . import texture_loader as tl


ADDON_ID = __package__

# What a suffix can be mapped to, in the order the menu lists them.
KIND_ITEMS = (
    (tl.BASE_COLOR, "Base Color", "Albedo, straight into Base Color"),
    (tl.ROUGHNESS, "Roughness", "Roughness"),
    (tl.METALLIC, "Metallic", "Metallic"),
    (tl.NORMAL, "Normal", "Tangent space normal map"),
    (tl.NORMAL_ROUGH, "Normal XY + Roughness",
     "R and G hold the normal, B holds roughness (_NRM)"),
    (tl.AO, "AO", "Ambient occlusion, drives the viewport AO modes"),
    (tl.HEIGHT, "Height", "Height or displacement, through a Bump node"),
    (tl.EMISSION, "Emission", "Emission colour"),
    (tl.OPACITY, "Opacity", "Alpha"),
    (tl.SPECULAR, "Specular", "Specular IOR level"),
    ("PACKED_MRO", "Packed R=Metal G=Rough B=AO", "Studio _spec and _MRO"),
    ("PACKED_ORM", "Packed R=AO G=Rough B=Metal", "Unreal style _ORM"),
    ("PACKED_RMA", "Packed R=Rough G=Metal B=AO", "_RMA"),
    (tl.PACKED_AUTO, "Packed (order from the letters)",
     "Read the channel order out of the suffix itself, like _ORM or _MRO"),
    (tl.IGNORE, "Ignore", "Never wire this map into the shader"),
)

KIND_LABELS = {identifier: label for identifier, label, _hint in KIND_ITEMS}


def get(context=None):
    """The add-on preferences, or None when the add-on is not registered."""
    context = context or bpy.context
    addon = context.preferences.addons.get(ADDON_ID)
    return addon.preferences if addon is not None else None


def ensure_defaults(prefs, force=False):
    """Fill the table from the built-in rules the first time it is opened."""
    if prefs is None:
        return
    if prefs.rules and not force:
        return
    prefs.rules.clear()
    for suffix, kind in tl.default_rules():
        rule = prefs.rules.add()
        rule.suffix = suffix
        if kind in KIND_LABELS:
            rule.kind = kind
    prefs.active_rule = 0


def rules_mapping(prefs):
    """The table as the dict texture_loader.set_rules expects."""
    if prefs is None:
        return {}
    mapping = {}
    for rule in prefs.rules:
        key = "".join(
            character for character in rule.suffix.lower()
            if character.isalnum()
        )
        if key:
            mapping[key] = rule.kind
    return mapping


def apply(context=None):
    """Push the user's table into the loader before a run."""
    prefs = get(context)
    ensure_defaults(prefs)
    tl.set_rules(rules_mapping(prefs))
    return prefs


def mark_dirty(context=None):
    """Tell Blender the preferences changed.

    Editing a field in the UI flags this by itself, but a change made from an
    operator does not, and Auto-Save Preferences would then drop the edit on
    the way out.
    """
    context = context or bpy.context
    try:
        context.preferences.is_dirty = True
    except AttributeError:
        pass


def _sync_name(self, context):
    self.name = self.suffix
    mark_dirty(context)


class MVM_SuffixRule(bpy.types.PropertyGroup):
    suffix: bpy.props.StringProperty(
        name="Suffix",
        description=(
            "Filename ending, without separators. \"basecolor\" matches "
            "_Base_Color, -basecolor and .BaseColor alike"
        ),
        update=_sync_name,
    )
    kind: bpy.props.EnumProperty(
        name="Map",
        description="Where a file with this suffix is linked",
        items=KIND_ITEMS,
        default=tl.BASE_COLOR,
    )


class MVM_ProjectRoot(bpy.types.PropertyGroup):
    path: bpy.props.StringProperty(
        name="Folder",
        description=(
            "A folder Find Textures may search for the asset an object came "
            "from, e.g. the review or projects drive"
        ),
        subtype="DIR_PATH",
        update=lambda self, context: mark_dirty(context),
    )


class MVM_OT_root_add(bpy.types.Operator):
    bl_idname = "mvm.root_add"
    bl_label = "Add Project Root"
    bl_description = "Add a folder to search for assets"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        prefs = get(context)
        if prefs is None:
            return {"CANCELLED"}
        prefs.roots.add()
        prefs.active_root = len(prefs.roots) - 1
        mark_dirty(context)
        return {"FINISHED"}


class MVM_OT_root_remove(bpy.types.Operator):
    bl_idname = "mvm.root_remove"
    bl_label = "Remove Project Root"
    bl_description = "Remove the selected folder"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        prefs = get(context)
        if prefs is None or not prefs.roots:
            return {"CANCELLED"}
        index = min(prefs.active_root, len(prefs.roots) - 1)
        prefs.roots.remove(index)
        prefs.active_root = min(index, len(prefs.roots) - 1)
        mark_dirty(context)
        return {"FINISHED"}


class MVM_UL_project_roots(bpy.types.UIList):
    bl_idname = "MVM_UL_project_roots"

    def draw_item(
        self, _context, layout, _data, item, _icon, _active_data,
        _active_prop, _index,
    ):
        layout.prop(item, "path", text="", emboss=True)


class MVM_UL_suffix_rules(bpy.types.UIList):
    bl_idname = "MVM_UL_suffix_rules"

    def draw_item(
        self, _context, layout, _data, item, _icon, _active_data,
        _active_prop, _index,
    ):
        row = layout.row(align=True)
        row.prop(item, "suffix", text="", emboss=True)
        row.prop(item, "kind", text="")

    def filter_items(self, _context, data, property_name):
        rules = getattr(data, property_name)
        flags = []
        if self.filter_name:
            needle = self.filter_name.lower()
            flags = [
                self.bitflag_filter_item if needle in rule.suffix.lower() else 0
                for rule in rules
            ]
        order = []
        if self.use_filter_sort_alpha:
            order = bpy.types.UI_UL_list.sort_items_by_name(rules, "suffix")
        return flags, order


class MVM_OT_rule_add(bpy.types.Operator):
    bl_idname = "mvm.rule_add"
    bl_label = "Add Suffix"
    bl_description = "Add an empty row to the suffix table"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        prefs = get(context)
        if prefs is None:
            return {"CANCELLED"}
        prefs.rules.add()
        prefs.active_rule = len(prefs.rules) - 1
        mark_dirty(context)
        return {"FINISHED"}


class MVM_OT_rule_remove(bpy.types.Operator):
    bl_idname = "mvm.rule_remove"
    bl_label = "Remove Suffix"
    bl_description = "Remove the selected row"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        prefs = get(context)
        if prefs is None or not prefs.rules:
            return {"CANCELLED"}
        index = min(prefs.active_rule, len(prefs.rules) - 1)
        prefs.rules.remove(index)
        prefs.active_rule = min(index, len(prefs.rules) - 1)
        mark_dirty(context)
        return {"FINISHED"}


class MVM_OT_rule_reset(bpy.types.Operator):
    bl_idname = "mvm.rule_reset"
    bl_label = "Reset To Defaults"
    bl_description = "Throw the table away and rebuild the built-in suffixes"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        prefs = get(context)
        if prefs is None:
            return {"CANCELLED"}
        ensure_defaults(prefs, force=True)
        mark_dirty(context)
        self.report({"INFO"}, "Suffix table reset to %d rules" % len(prefs.rules))
        return {"FINISHED"}

    def invoke(self, context, _event):
        return context.window_manager.invoke_confirm(self, _event)


def draw_rules(layout, prefs):
    if prefs is None:
        layout.label(text="Add-on preferences unavailable", icon="ERROR")
        return
    layout.label(text="Texture Suffixes")
    row = layout.row()
    row.template_list(
        "MVM_UL_suffix_rules", "", prefs, "rules", prefs, "active_rule",
        rows=12,
    )
    side = row.column(align=True)
    side.operator("mvm.rule_add", text="", icon="ADD")
    side.operator("mvm.rule_remove", text="", icon="REMOVE")
    side.separator()
    side.operator("mvm.rule_reset", text="", icon="LOOP_BACK")
    footer = layout.row()
    footer.label(text="%d suffixes" % len(prefs.rules))
    footer.label(text="Type the ending without _ or -, e.g. basecolor, nrm, d")

    auto_save = bpy.context.preferences.use_preferences_save
    save = layout.row()
    if auto_save:
        save.label(text="Saved with your preferences", icon="CHECKMARK")
    else:
        save.alert = True
        save.label(
            text="Auto-Save Preferences is off - save or lose these on exit",
            icon="ERROR",
        )
    save.operator("wm.save_userpref", text="Save Preferences", icon="FILE_TICK")

    layout.separator()
    layout.label(text="Project Roots")
    layout.label(
        text="Folders searched for the asset an object was imported from",
        icon="INFO",
    )
    row = layout.row()
    row.template_list(
        "MVM_UL_project_roots", "", prefs, "roots", prefs, "active_root",
        rows=3,
    )
    side = row.column(align=True)
    side.operator("mvm.root_add", text="", icon="ADD")
    side.operator("mvm.root_remove", text="", icon="REMOVE")


class MVM_OT_suffix_settings(bpy.types.Operator):
    bl_idname = "mvm.suffix_settings"
    bl_label = "Settings"
    bl_description = "Edit the texture suffixes Find Textures recognises"

    def invoke(self, context, _event):
        ensure_defaults(get(context))
        return context.window_manager.invoke_props_dialog(self, width=560)

    def draw(self, context):
        draw_rules(self.layout, get(context))

    def execute(self, context):
        apply(context)
        mark_dirty(context)
        return {"FINISHED"}


class MVM_Preferences(bpy.types.AddonPreferences):
    bl_idname = ADDON_ID

    rules: bpy.props.CollectionProperty(type=MVM_SuffixRule)
    active_rule: bpy.props.IntProperty(default=0)
    roots: bpy.props.CollectionProperty(type=MVM_ProjectRoot)
    active_root: bpy.props.IntProperty(default=0)

    def draw(self, context):
        draw_rules(self.layout, self)


CLASSES = (
    MVM_SuffixRule,
    MVM_ProjectRoot,
    MVM_UL_project_roots,
    MVM_OT_root_add,
    MVM_OT_root_remove,
    MVM_UL_suffix_rules,
    MVM_OT_rule_add,
    MVM_OT_rule_remove,
    MVM_OT_rule_reset,
    MVM_OT_suffix_settings,
    MVM_Preferences,
)
