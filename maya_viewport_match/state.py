_SNAPSHOT = None


def _is_valid_rna(value):
    try:
        return value is not None and value.as_pointer() != 0
    except ReferenceError:
        return False


def is_active(scene):
    if _SNAPSHOT is None:
        return False
    saved_scene = _SNAPSHOT["scene"]
    return _is_valid_rna(saved_scene) and saved_scene == scene


def capture(context):
    global _SNAPSHOT
    if _SNAPSHOT is not None:
        if _is_valid_rna(_SNAPSHOT["scene"]):
            return _SNAPSHOT
        _SNAPSHOT = None

    viewports = []
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                space = area.spaces.active
                viewports.append((space, space.shading.type))
    _SNAPSHOT = {"scene": context.scene, "viewports": viewports}
    return _SNAPSHOT


def restore(context):
    global _SNAPSHOT
    snapshot = _SNAPSHOT
    if snapshot is None:
        return False
    _SNAPSHOT = None

    for space, shading_type in snapshot["viewports"]:
        try:
            space.shading.type = shading_type
        except (AttributeError, ReferenceError):
            pass

    saved_scene = snapshot["scene"]
    if _is_valid_rna(saved_scene):
        saved_scene["mvm_match_mode"] = "NONE"
    if _is_valid_rna(context.scene):
        context.scene["mvm_match_mode"] = "NONE"
    return True
