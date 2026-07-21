import bpy

from .coordinates import MAYA_TO_BLENDER_SCALE
from .coordinates import maya_camera_matrix_to_blender


CALIBRATION_CAMERA = "MVM_Calibration"
INCH_TO_MM = 25.4


def apply_maya_camera(scene, matrix, attrs, width, height, camera_name=None):
    width = int(width)
    height = int(height)
    if width <= 0 or height <= 0:
        raise ValueError("Camera resolution must be positive")

    name = camera_name or CALIBRATION_CAMERA
    camera = bpy.data.objects.get(name)
    if camera is not None and camera.type != "CAMERA":
        raise TypeError(f"Object {name!r} exists and is not a camera")
    if camera is None:
        data = bpy.data.cameras.new(name)
        camera = bpy.data.objects.new(name, data)
        scene.collection.objects.link(camera)
    elif camera.name not in scene.objects:
        scene.collection.objects.link(camera)

    camera.matrix_world = maya_camera_matrix_to_blender(matrix)
    camera.data.type = "ORTHO" if attrs.get("orthographic") else "PERSP"
    camera.data.lens = float(attrs.get("focalLength", 35.0))
    camera.data.sensor_width = (
        float(attrs.get("horizontalFilmAperture", 1.41732)) * INCH_TO_MM
    )
    camera.data.sensor_height = (
        float(attrs.get("verticalFilmAperture", 0.94488)) * INCH_TO_MM
    )
    camera.data.sensor_fit = "HORIZONTAL"
    camera.data.clip_start = max(
        float(attrs.get("nearClipPlane", 1.0)) * MAYA_TO_BLENDER_SCALE,
        0.0001,
    )
    camera.data.clip_end = (
        float(attrs.get("farClipPlane", 1000000.0)) * MAYA_TO_BLENDER_SCALE
    )
    camera.data.ortho_scale = (
        float(attrs.get("orthographicWidth", 10.0)) * MAYA_TO_BLENDER_SCALE
    )
    camera.data.shift_x = float(attrs.get("filmTranslateH", 0.0))
    camera.data.shift_y = float(attrs.get("filmTranslateV", 0.0))

    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.pixel_aspect_x = 1.0
    scene.render.pixel_aspect_y = 1.0
    scene.camera = camera
    return camera
