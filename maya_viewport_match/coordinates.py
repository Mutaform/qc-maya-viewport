from mathutils import Matrix, Vector


MAYA_TO_BLENDER_SCALE = 0.01
AXIS_MATRIX = Matrix((
    (1.0, 0.0, 0.0),
    (0.0, 0.0, -1.0),
    (0.0, 1.0, 0.0),
))


def maya_point_to_blender(point):
    return (AXIS_MATRIX @ Vector(point)) * MAYA_TO_BLENDER_SCALE


def maya_camera_matrix_to_blender(values):
    if len(values) != 16:
        raise ValueError("Maya camera matrix must contain 16 values")
    maya_basis = Matrix((
        values[0:3],
        values[4:7],
        values[8:11],
    )).transposed()
    blender_basis = AXIS_MATRIX @ maya_basis
    location = maya_point_to_blender(values[12:15])
    return Matrix((
        (*blender_basis.col[0], 0.0),
        (*blender_basis.col[1], 0.0),
        (*blender_basis.col[2], 0.0),
        (*location, 1.0),
    )).transposed()
