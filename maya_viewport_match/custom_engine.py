import bpy
import bmesh
import gpu
import numpy as np
import time
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix

from . import state


_HANDLER = None
_CPU_GEOMETRY = {}
_GPU_GEOMETRY = {}
_GPU_OUTLINE_MASKS = {}
_OUTLINE_OFFSCREEN = None
_OUTLINE_OFFSCREEN_SIZE = None
_EDIT_OVERLAY_BATCHES = {}
_EDIT_OVERLAY_DIRTY = set()
_EDIT_DIRTY = set()
_EDIT_SYNC_SKIP = set()
_EDIT_TOPOLOGY = {}
_LAST_ERROR = ""
_DRAW_COUNT = 0
_LAST_TRIANGLES = 0
_LAST_TIMINGS = {}
# Keep the overlay only a few 24-bit depth-buffer steps above the surface.
_FACE_DEPTH_BIAS = 2.5e-7
_EDGE_DEPTH_BIAS = 5.0e-7
_VERTEX_DEPTH_BIAS = 7.5e-7
_DEPTH_BIAS_REFERENCE_DISTANCE = 4.0
_DEPTH_BIAS_MIN_SCALE = 0.25
_DEPTH_BIAS_MAX_SCALE = 64.0
_PARAMS = {
    "diffuse": 0.50,
    "specular": 0.30,
    "exponent": 44.0,
    "fill": 0.0,
    "light_x": 0.0,
    "light_y": 0.25,
    "ao_only": 0,
    "use_ao": 1,
    "default_material": 0,
    "directx_normal": 0,
}


def _depsgraph_geometry_update(scene, depsgraph):
    if _HANDLER is None:
        return
    changed_objects = set()
    geometry_objects = set()
    unresolved_mesh = False
    for update in depsgraph.updates:
        changed = getattr(update.id, "original", update.id)
        pointers = set()
        if isinstance(changed, bpy.types.Object) and changed.type == "MESH":
            pointers.add(changed.as_pointer())
        elif isinstance(changed, bpy.types.Mesh):
            matches = [
                obj for obj in scene.objects
                if obj.type == "MESH"
                and getattr(obj.data, "original", obj.data) == changed
            ]
            pointers.update(obj.as_pointer() for obj in matches)
            unresolved_mesh |= bool(update.is_updated_geometry and not matches)
        changed_objects.update(pointers)
        if update.is_updated_geometry:
            geometry_objects.update(pointers)

    if unresolved_mesh:
        _CPU_GEOMETRY.clear()
        _EDIT_OVERLAY_DIRTY.update(
            obj.as_pointer() for obj in scene.objects if obj.type == "MESH"
        )
    _EDIT_OVERLAY_DIRTY.update(changed_objects)
    for pointer in geometry_objects:
        if pointer in _EDIT_SYNC_SKIP:
            _EDIT_SYNC_SKIP.discard(pointer)
            continue
        for key in [key for key in _CPU_GEOMETRY if key[0] == pointer]:
            del _CPU_GEOMETRY[key]
        obj = next(
            (item for item in scene.objects if item.as_pointer() == pointer),
            None,
        )
        if obj is not None and obj.data.is_editmode:
            _EDIT_DIRTY.add(pointer)


def _remove_depsgraph_handlers():
    handlers = bpy.app.handlers.depsgraph_update_post
    handlers[:] = [
        handler for handler in handlers
        if not (
            getattr(handler, "__name__", "") == "_depsgraph_geometry_update"
            and "maya_viewport_match" in getattr(handler, "__module__", "")
        )
    ]


def _track_edit_topology(obj):
    pointer = obj.as_pointer()
    mesh = obj.data
    if not mesh.is_editmode:
        _EDIT_TOPOLOGY.pop(pointer, None)
        return

    bm = bmesh.from_edit_mesh(mesh)
    signature = (len(bm.verts), len(bm.edges), len(bm.faces))
    if _EDIT_TOPOLOGY.get(pointer) == signature:
        return

    _EDIT_TOPOLOGY[pointer] = signature
    for key in [key for key in _CPU_GEOMETRY if key[0] == pointer]:
        del _CPU_GEOMETRY[key]
    _EDIT_OVERLAY_DIRTY.add(pointer)
    _EDIT_DIRTY.add(pointer)


def _configure_texture(texture):
    texture.filter_mode(True)
    texture.anisotropic_filter(True)


def _gpu_texture(image, fallback):
    if image is not None:
        texture = gpu.texture.from_image(image)
    else:
        buffer = gpu.types.Buffer("FLOAT", 4, fallback)
        texture = gpu.types.GPUTexture((1, 1), format="RGBA32F", data=buffer)
    _configure_texture(texture)
    return texture


def _create_shader():
    interface = gpu.types.GPUStageInterfaceInfo("mvm_safe_viewport_interface")
    interface.smooth("VEC3", "viewPosition")
    interface.smooth("VEC3", "viewNormal")
    interface.smooth("VEC4", "viewTangent")
    interface.smooth("VEC2", "texCoord")

    info = gpu.types.GPUShaderCreateInfo()
    info.push_constant("MAT4", "mvp")
    info.push_constant("MAT4", "modelView")
    info.push_constant("MAT3", "normalMatrix")
    info.push_constant("FLOAT", "diffuseLevel")
    info.push_constant("FLOAT", "specularLevel")
    info.push_constant("FLOAT", "blinnExponent")
    info.push_constant("FLOAT", "fillLevel")
    info.push_constant("FLOAT", "lightX")
    info.push_constant("FLOAT", "lightY")
    info.push_constant("INT", "aoEnabled")
    info.push_constant("INT", "aoOnly")
    info.push_constant("INT", "useAo")
    info.push_constant("INT", "defaultMaterial")
    info.push_constant("INT", "isPerspective")
    info.push_constant("INT", "directXNormal")
    info.push_constant("INT", "alphaEnabled")
    info.push_constant("INT", "alphaChannel")
    info.push_constant("INT", "alphaClip")
    info.push_constant("FLOAT", "materialAlpha")
    info.sampler(0, "FLOAT_2D", "normalTexture")
    info.sampler(1, "FLOAT_2D", "aoTexture")
    info.sampler(2, "FLOAT_2D", "alphaTexture")
    info.vertex_in(0, "VEC3", "position")
    info.vertex_in(1, "VEC3", "normal")
    info.vertex_in(2, "VEC4", "tangent")
    info.vertex_in(3, "VEC2", "uv")
    info.vertex_out(interface)
    info.fragment_out(0, "VEC4", "fragColor")
    info.vertex_source(
        """
        void main()
        {
            vec4 view = modelView * vec4(position, 1.0);
            viewPosition = view.xyz;
            viewNormal = normalize(normalMatrix * normal);
            viewTangent = vec4(normalize(normalMatrix * tangent.xyz), tangent.w);
            texCoord = uv;
            gl_Position = mvp * vec4(position, 1.0);
        }
        """
    )
    info.fragment_source(
        """
        void main()
        {
            float opacity = 1.0;
            if (defaultMaterial == 0) {
                opacity = materialAlpha;
                if (alphaEnabled != 0) {
                    vec4 alphaSample = texture(alphaTexture, texCoord);
                    opacity = alphaChannel != 0
                        ? alphaSample.a : alphaSample.r;
                }
            }
            if (alphaClip != 0) {
                if (opacity < 0.5) {
                    discard;
                }
                opacity = 1.0;
            }
            if (opacity <= 0.001) {
                discard;
            }
            if (aoOnly != 0) {
                vec3 color = aoEnabled != 0
                    ? texture(aoTexture, texCoord).rgb : vec3(1.0);
                fragColor = vec4(color, opacity);
                return;
            }
            vec3 n = normalize(viewNormal);
            if (!gl_FrontFacing) {
                n = -n;
            }
            if (defaultMaterial == 0) {
                vec3 mapNormal = texture(normalTexture, texCoord).rgb * 2.0 - 1.0;
                if (directXNormal != 0) {
                    mapNormal.y = -mapNormal.y;
                }
                vec3 t = normalize(viewTangent.xyz - n * dot(n, viewTangent.xyz));
                vec3 b = normalize(cross(n, t)) * viewTangent.w;
                n = normalize(mat3(t, b, n) * mapNormal);
            }

            vec3 viewDirection = isPerspective != 0
                ? normalize(-viewPosition) : vec3(0.0, 0.0, 1.0);
            if (dot(n, viewDirection) < 0.0) {
                n = -n;
            }
            vec3 keyDirection = normalize(vec3(lightX, lightY, 1.0));
            vec3 fillDirection = normalize(vec3(-0.34, 0.28, 0.90));
            float keyDiffuse = max(dot(n, keyDirection), 0.0);
            float fillDiffuse = max(dot(n, fillDirection), 0.0);
            vec3 baseColor = defaultMaterial != 0
                ? vec3(0.5)
                : (aoEnabled != 0 && useAo != 0
                    ? texture(aoTexture, texCoord).rgb * 2.0 : vec3(1.0));
            vec3 diffuse = baseColor * diffuseLevel
                * (keyDiffuse + fillLevel * fillDiffuse);
            vec3 halfVector = normalize(keyDirection + viewDirection);
            float specular = defaultMaterial == 0
                ? specularLevel * pow(max(dot(n, halfVector), 0.0), blinnExponent) : 0.0;
            vec3 color = diffuse + vec3(specular);
            fragColor = vec4(color, opacity);
        }
        """
    )
    return gpu.shader.create_from_info(info)


def _create_overlay_shader():
    interface = gpu.types.GPUStageInterfaceInfo("mvm_edit_overlay_interface")
    interface.smooth("VEC4", "vertexColor")

    info = gpu.types.GPUShaderCreateInfo()
    info.push_constant("MAT4", "mvp")
    info.push_constant("FLOAT", "depthBias")
    info.vertex_in(0, "VEC3", "position")
    info.vertex_in(1, "VEC4", "color")
    info.vertex_out(interface)
    info.fragment_out(0, "VEC4", "fragColor")
    info.vertex_source(
        """
        void main()
        {
            vertexColor = color;
            gl_Position = mvp * vec4(position, 1.0);
            gl_Position.z -= depthBias * gl_Position.w;
        }
        """
    )
    info.fragment_source(
        """
        void main()
        {
            fragColor = vertexColor;
        }
        """
    )
    return gpu.shader.create_from_info(info)


def _create_outline_mask_shader():
    info = gpu.types.GPUShaderCreateInfo()
    info.push_constant("MAT4", "mvp")
    info.vertex_in(0, "VEC3", "position")
    info.fragment_out(0, "VEC4", "fragColor")
    info.vertex_source(
        """
        void main()
        {
            gl_Position = mvp * vec4(position, 1.0);
        }
        """
    )
    info.fragment_source(
        """
        void main()
        {
            fragColor = vec4(1.0);
        }
        """
    )
    return gpu.shader.create_from_info(info)


def _create_outline_composite_shader():
    interface = gpu.types.GPUStageInterfaceInfo("mvm_outline_composite_interface")
    interface.smooth("VEC2", "texCoord")

    info = gpu.types.GPUShaderCreateInfo()
    info.push_constant("INT", "outlineRadius")
    info.push_constant("VEC4", "outlineColor")
    info.sampler(0, "FLOAT_2D", "maskTexture")
    info.vertex_in(0, "VEC2", "position")
    info.vertex_in(1, "VEC2", "uv")
    info.vertex_out(interface)
    info.fragment_out(0, "VEC4", "fragColor")
    info.vertex_source(
        """
        void main()
        {
            texCoord = uv;
            gl_Position = vec4(position, 0.0, 1.0);
        }
        """
    )
    info.fragment_source(
        """
        void main()
        {
            ivec2 size = textureSize(maskTexture, 0);
            ivec2 pixel = clamp(
                ivec2(texCoord * vec2(size)), ivec2(0), size - ivec2(1));
            float minimumMask = 1.0;
            float maximumMask = 0.0;
            for (int y = -2; y <= 2; ++y) {
                for (int x = -2; x <= 2; ++x) {
                    if (abs(x) > outlineRadius || abs(y) > outlineRadius) {
                        continue;
                    }
                    ivec2 samplePixel = clamp(
                        pixel + ivec2(x, y), ivec2(0), size - ivec2(1));
                    float mask = texelFetch(maskTexture, samplePixel, 0).r;
                    minimumMask = min(minimumMask, mask);
                    maximumMask = max(maximumMask, mask);
                }
            }
            if (maximumMask - minimumMask < 0.5) {
                discard;
            }
            fragColor = outlineColor;
        }
        """
    )
    return gpu.shader.create_from_info(info)


def _biased_projection(projection, depth_bias):
    biased = projection.copy()
    for column in range(4):
        biased[2][column] -= depth_bias * biased[3][column]
    return biased


def _scaled_depth_bias(region_data, depth_bias):
    distance = max(float(region_data.view_distance), 0.01)
    scale = (_DEPTH_BIAS_REFERENCE_DISTANCE / distance) ** 2
    scale = min(max(scale, _DEPTH_BIAS_MIN_SCALE), _DEPTH_BIAS_MAX_SCALE)
    return depth_bias * scale


def _geometry_batch(shader, key, data):
    cached = _GPU_GEOMETRY.get(key)
    if cached is not None and cached[0] is data:
        return cached[1], False
    batch = batch_for_shader(shader, "TRIS", data)
    _GPU_GEOMETRY[key] = (data, batch)
    return batch, True


def _edit_overlay_batches(
    obj, bm, face_shader, line_shader, point_shader,
    select_mode, colors, edge_flags, depsgraph,
):
    pointer = obj.as_pointer()
    mesh = obj.data
    active_element = bm.select_history.active
    signature = (
        tuple(select_mode),
        len(mesh.vertices), len(mesh.edges), len(mesh.polygons),
        mesh.total_vert_sel,
        mesh.total_edge_sel,
        mesh.total_face_sel,
        type(active_element).__name__ if active_element is not None else "",
        active_element.index if active_element is not None else -1,
        tuple(edge_flags),
        tuple(colors.values()),
    )
    cached = _EDIT_OVERLAY_BATCHES.get(pointer)
    if (
        cached is not None
        and pointer not in _EDIT_OVERLAY_DIRTY
        and cached[0] == signature
    ):
        return cached[1], False

    _EDIT_SYNC_SKIP.add(pointer)
    obj.update_from_editmode()
    depsgraph.update()
    batches = {"faces": None, "edges": None, "vertices": None, "count": 0}
    vertex_count = len(mesh.vertices)
    edge_count = len(mesh.edges)
    polygon_count = len(mesh.polygons)
    coordinates = np.empty(vertex_count * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", coordinates)
    coordinates = coordinates.reshape((-1, 3))

    if select_mode[2]:
        mesh.calc_loop_triangles()
        triangle_count = len(mesh.loop_triangles)
        triangle_vertices = np.empty(triangle_count * 3, dtype=np.int32)
        triangle_polygons = np.empty(triangle_count, dtype=np.int32)
        polygon_selected = np.empty(polygon_count, dtype=np.bool_)
        polygon_hidden = np.empty(polygon_count, dtype=np.bool_)
        mesh.loop_triangles.foreach_get("vertices", triangle_vertices)
        mesh.loop_triangles.foreach_get("polygon_index", triangle_polygons)
        mesh.polygons.foreach_get("select", polygon_selected)
        mesh.polygons.foreach_get("hide", polygon_hidden)
        visible_selected = (
            polygon_selected[triangle_polygons]
            & ~polygon_hidden[triangle_polygons]
        )
        triangle_vertices = triangle_vertices.reshape((-1, 3))[visible_selected]
        if triangle_vertices.size:
            positions = np.ascontiguousarray(
                coordinates[triangle_vertices].reshape((-1, 3)),
                dtype=np.float32,
            )
            vertex_colors = np.tile(
                np.asarray(colors["face_selected"], dtype=np.float32),
                (len(positions), 1),
            )
            batches["faces"] = batch_for_shader(
                face_shader,
                "TRIS",
                {"position": positions, "color": vertex_colors},
            )
            batches["count"] += len(positions) // 3

    edge_vertices = np.empty(edge_count * 2, dtype=np.int32)
    edge_selected = np.empty(edge_count, dtype=np.bool_)
    edge_hidden = np.empty(edge_count, dtype=np.bool_)
    edge_sharp = np.empty(edge_count, dtype=np.bool_)
    edge_seam = np.empty(edge_count, dtype=np.bool_)
    mesh.edges.foreach_get("vertices", edge_vertices)
    mesh.edges.foreach_get("select", edge_selected)
    mesh.edges.foreach_get("hide", edge_hidden)
    mesh.edges.foreach_get("use_edge_sharp", edge_sharp)
    mesh.edges.foreach_get("use_seam", edge_seam)
    visible_edges = np.flatnonzero(~edge_hidden)
    if visible_edges.size:
        edge_vertices = edge_vertices.reshape((-1, 2))[visible_edges]
        positions = np.ascontiguousarray(
            coordinates[edge_vertices].reshape((-1, 3)), dtype=np.float32
        )
        edge_colors = np.tile(
            np.asarray(colors["wire"], dtype=np.float32),
            (len(visible_edges), 2, 1),
        )
        show_sharp, show_seam = edge_flags
        if show_sharp:
            edge_colors[edge_sharp[visible_edges]] = colors["sharp"]
        if show_seam:
            edge_colors[edge_seam[visible_edges]] = colors["seam"]
        edge_colors[edge_selected[visible_edges]] = colors["edge_selected"]
        if type(active_element).__name__ == "BMEdge" and active_element.index >= 0:
            active_match = np.flatnonzero(visible_edges == active_element.index)
            if active_match.size:
                edge_colors[active_match[0]] = colors["active"]
        vertex_colors = np.ascontiguousarray(
            edge_colors.reshape((-1, 4)), dtype=np.float32
        )
        batches["edges"] = batch_for_shader(
            line_shader, "LINES", {"pos": positions, "color": vertex_colors}
        )
        batches["count"] += len(positions) // 2

    if select_mode[0]:
        vertex_selected = np.empty(vertex_count, dtype=np.bool_)
        vertex_hidden = np.empty(vertex_count, dtype=np.bool_)
        mesh.vertices.foreach_get("select", vertex_selected)
        mesh.vertices.foreach_get("hide", vertex_hidden)
        visible_vertices = np.flatnonzero(~vertex_hidden)
        if visible_vertices.size:
            positions = np.ascontiguousarray(
                coordinates[visible_vertices], dtype=np.float32
            )
            vertex_colors = np.tile(
                np.asarray(colors["vertex"], dtype=np.float32),
                (len(visible_vertices), 1),
            )
            vertex_colors[vertex_selected[visible_vertices]] = colors[
                "vertex_selected"
            ]
            if type(active_element).__name__ == "BMVert" and active_element.index >= 0:
                active_match = np.flatnonzero(
                    visible_vertices == active_element.index
                )
                if active_match.size:
                    vertex_colors[active_match[0]] = colors["active"]
            vertex_colors = np.ascontiguousarray(vertex_colors, dtype=np.float32)
            batches["vertices"] = batch_for_shader(
                point_shader,
                "POINTS",
                {"pos": positions, "color": vertex_colors},
            )
            batches["count"] += len(positions)

    _EDIT_OVERLAY_BATCHES[pointer] = (signature, batches)
    _EDIT_OVERLAY_DIRTY.discard(pointer)
    return batches, True


def _draw_edit_overlays(context, view, projection, depsgraph):
    space = context.space_data
    if space is None or not space.overlay.show_overlays:
        return 0, 0.0

    edit_objects = [
        obj for obj in context.objects_in_mode_unique_data
        if obj.type == "MESH" and obj.data.is_editmode and obj.visible_get()
    ]
    if not edit_objects:
        _EDIT_OVERLAY_BATCHES.clear()
        return 0, 0.0

    face_shader = _create_overlay_shader()
    line_shader = gpu.shader.from_builtin("POLYLINE_SMOOTH_COLOR")
    point_shader = gpu.shader.from_builtin("POINT_FLAT_COLOR")
    select_mode = context.tool_settings.mesh_select_mode
    theme = context.preferences.themes[0].view_3d
    edge_width = max(1.0, float(getattr(theme, "edge_width", 1.0)))
    vertex_size = max(3.0, float(getattr(theme, "vertex_size", 3.0)))
    colors = {
        "wire": (*theme.wire_edit[:], 1.0),
        "edge_selected": (*theme.edge_select[:], 1.0),
        "vertex": (*theme.vertex[:], 1.0),
        "vertex_selected": (*theme.vertex_select[:], 1.0),
        "active": (*theme.edge_mode_select[:], 1.0),
        "face_selected": tuple(theme.face_select),
        "sharp": (*theme.sharp[:], 1.0),
        "seam": (*theme.seam[:], 1.0),
    }
    edge_flags = (
        bool(space.overlay.show_edge_sharp),
        bool(space.overlay.show_edge_seams),
    )
    face_depth_bias = _scaled_depth_bias(
        context.region_data, _FACE_DEPTH_BIAS
    )
    edge_depth_bias = _scaled_depth_bias(
        context.region_data, _EDGE_DEPTH_BIAS
    )
    vertex_depth_bias = _scaled_depth_bias(
        context.region_data, _VERTEX_DEPTH_BIAS
    )
    element_count = 0
    rebuild_time = 0.0
    active_pointers = {obj.as_pointer() for obj in edit_objects}
    for pointer in [key for key in _EDIT_OVERLAY_BATCHES if key not in active_pointers]:
        del _EDIT_OVERLAY_BATCHES[pointer]

    gpu.state.blend_set("ALPHA")
    gpu.state.depth_mask_set(False)
    gpu.state.depth_test_set("NONE" if space.shading.show_xray else "LESS_EQUAL")
    try:
        for obj in edit_objects:
            bm = bmesh.from_edit_mesh(obj.data)
            model_view = view @ obj.matrix_world
            rebuild_start = time.perf_counter()
            batches, rebuilt = _edit_overlay_batches(
                obj,
                bm,
                face_shader,
                line_shader,
                point_shader,
                select_mode,
                colors,
                edge_flags,
                depsgraph,
            )
            if rebuilt:
                rebuild_time += time.perf_counter() - rebuild_start
            if batches["faces"] is not None:
                face_shader.bind()
                face_shader.uniform_float("mvp", projection @ model_view)
                face_shader.uniform_float("depthBias", face_depth_bias)
                batches["faces"].draw(face_shader)
            if batches["edges"] is not None:
                with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
                    gpu.matrix.load_matrix(model_view)
                    gpu.matrix.load_projection_matrix(
                        _biased_projection(projection, edge_depth_bias)
                    )
                    line_shader.bind()
                    line_shader.uniform_float(
                        "viewportSize",
                        (float(context.region.width), float(context.region.height)),
                    )
                    line_shader.uniform_float("lineWidth", edge_width)
                    batches["edges"].draw(line_shader)
            if batches["vertices"] is not None:
                with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
                    gpu.matrix.load_matrix(model_view)
                    gpu.matrix.load_projection_matrix(
                        _biased_projection(projection, vertex_depth_bias)
                    )
                    point_shader.bind()
                    gpu.state.point_size_set(vertex_size)
                    batches["vertices"].draw(point_shader)
            element_count += batches["count"]
    finally:
        gpu.state.line_width_set(1.0)
        gpu.state.point_size_set(1.0)
        gpu.state.blend_set("NONE")
    return element_count, rebuild_time


def _normal_image(material):
    if material is None or not material.use_nodes:
        return None
    for node in material.node_tree.nodes:
        if node.type != "NORMAL_MAP":
            continue
        color = node.inputs.get("Color")
        if color and color.is_linked:
            source = color.links[0].from_node
            if source.type == "TEX_IMAGE":
                return source.image
    return None


def _ao_image(material):
    if material is None or not material.use_nodes:
        return None
    for node in material.node_tree.nodes:
        if node.type != "BSDF_PRINCIPLED":
            continue
        base_color = node.inputs.get("Base Color")
        if base_color and base_color.is_linked:
            source = base_color.links[0].from_node
            if source.type == "TEX_IMAGE":
                return source.image
    return None


def _alpha_settings(material):
    if material is None or not material.use_nodes:
        return None, 0, 1.0
    for node in material.node_tree.nodes:
        if node.type != "BSDF_PRINCIPLED":
            continue
        alpha = node.inputs.get("Alpha")
        if alpha is None:
            return None, 0, 1.0
        default_alpha = float(alpha.default_value)
        if not alpha.is_linked:
            return None, 0, default_alpha
        link = alpha.links[0]
        source = link.from_node
        if source.type == "TEX_IMAGE" and source.image is not None:
            channel = 1 if link.from_socket.name == "Alpha" else 0
            return source.image, channel, default_alpha
        return None, 0, default_alpha
    return None, 0, 1.0


def _triangulate_ngons(mesh):
    if not any(polygon.loop_total > 4 for polygon in mesh.polygons):
        return False

    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        ngons = [face for face in bm.faces if len(face.verts) > 4]
        if not ngons:
            return False
        bmesh.ops.triangulate(bm, faces=ngons)
        bm.to_mesh(mesh)
        mesh.update()
        return True
    finally:
        bm.free()


def _geometry(obj, material_index, depsgraph):
    source_mesh = obj.data
    pointer = obj.as_pointer()
    key = (pointer, material_index)
    _track_edit_topology(obj)
    cached = _CPU_GEOMETRY.get(key)
    if cached is not None:
        return cached
    temporary = None
    evaluated = None
    try:
        if source_mesh.is_editmode and pointer in _EDIT_DIRTY:
            _EDIT_DIRTY.discard(pointer)
            _EDIT_SYNC_SKIP.add(pointer)
            obj.update_from_editmode()
            depsgraph.update()
        evaluated = obj.evaluated_get(depsgraph)
        temporary = evaluated.to_mesh(
            preserve_all_data_layers=True,
            depsgraph=depsgraph,
        )
        mesh = temporary
        has_valid_uv = bool(
            mesh.uv_layers
            and mesh.uv_layers.active is not None
            and len(mesh.uv_layers.active.data) >= len(mesh.loops)
        )
        if source_mesh.is_editmode and not mesh.loops:
            evaluated.to_mesh_clear()
            evaluated = None
            edit_copy = bmesh.from_edit_mesh(source_mesh).copy()
            temporary = bpy.data.meshes.new("MVM Edit Mesh")
            edit_copy.to_mesh(temporary)
            edit_copy.free()
            mesh = temporary
        if has_valid_uv and _triangulate_ngons(mesh):
            has_valid_uv = bool(
                mesh.uv_layers
                and mesh.uv_layers.active is not None
                and len(mesh.uv_layers.active.data) >= len(mesh.loops)
            )
        uv_data = mesh.uv_layers.active.data if has_valid_uv else None

        mesh.calc_loop_triangles()
        if has_valid_uv:
            mesh.calc_tangents(uvmap=mesh.uv_layers.active.name)
        triangle_count = len(mesh.loop_triangles)
        loop_count = len(mesh.loops)
        vertex_count = len(mesh.vertices)
        triangle_loops = np.empty(triangle_count * 3, dtype=np.int32)
        triangle_materials = np.empty(triangle_count, dtype=np.int32)
        mesh.loop_triangles.foreach_get("loops", triangle_loops)
        mesh.loop_triangles.foreach_get("material_index", triangle_materials)
        triangle_loops = triangle_loops.reshape((-1, 3))
        loop_indices = triangle_loops[
            triangle_materials == material_index
        ].reshape(-1)
        if loop_indices.size == 0:
            return None

        loop_vertices = np.empty(loop_count, dtype=np.int32)
        positions = np.empty(vertex_count * 3, dtype=np.float32)
        normals = np.empty(loop_count * 3, dtype=np.float32)
        mesh.loops.foreach_get("vertex_index", loop_vertices)
        mesh.vertices.foreach_get("co", positions)
        mesh.corner_normals.foreach_get("vector", normals)
        positions = positions.reshape((-1, 3))[loop_vertices[loop_indices]]
        normals = normals.reshape((-1, 3))[loop_indices]

        if has_valid_uv:
            tangents = np.empty(loop_count * 3, dtype=np.float32)
            tangent_signs = np.empty(loop_count, dtype=np.float32)
            uvs = np.empty(loop_count * 2, dtype=np.float32)
            mesh.loops.foreach_get("tangent", tangents)
            mesh.loops.foreach_get("bitangent_sign", tangent_signs)
            uv_data.foreach_get("uv", uvs)
            tangents = tangents.reshape((-1, 3))[loop_indices]
            tangents = np.column_stack(
                (tangents, tangent_signs[loop_indices])
            ).astype(np.float32, copy=False)
            uvs = uvs.reshape((-1, 2))[loop_indices]
        else:
            references = np.zeros_like(normals)
            references[:, 2] = 1.0
            references[np.abs(normals[:, 2]) > 0.999] = (0.0, 1.0, 0.0)
            tangent_xyz = np.cross(references, normals)
            lengths = np.linalg.norm(tangent_xyz, axis=1, keepdims=True)
            tangent_xyz /= np.maximum(lengths, 1.0e-8)
            tangents = np.column_stack(
                (tangent_xyz, np.ones(len(tangent_xyz), dtype=np.float32))
            ).astype(np.float32, copy=False)
            uvs = np.zeros((len(loop_indices), 2), dtype=np.float32)

        data = {
            "position": np.ascontiguousarray(positions, dtype=np.float32),
            "normal": np.ascontiguousarray(normals, dtype=np.float32),
            "tangent": np.ascontiguousarray(tangents, dtype=np.float32),
            "uv": np.ascontiguousarray(uvs, dtype=np.float32),
        }
        _CPU_GEOMETRY[key] = data
        return data
    finally:
        if evaluated is not None:
            evaluated.to_mesh_clear()
        elif temporary is not None:
            bpy.data.meshes.remove(temporary)


def _outline_mask_batch(shader, key, data):
    cached = _GPU_OUTLINE_MASKS.get(key)
    if cached is not None and cached[0] is data:
        return cached[1]
    batch = batch_for_shader(
        shader,
        "TRIS",
        {"position": data["position"]},
    )
    _GPU_OUTLINE_MASKS[key] = (data, batch)
    return batch


def _outline_offscreen(width, height):
    global _OUTLINE_OFFSCREEN, _OUTLINE_OFFSCREEN_SIZE
    size = (width, height)
    if _OUTLINE_OFFSCREEN is not None and _OUTLINE_OFFSCREEN_SIZE != size:
        _OUTLINE_OFFSCREEN.free()
        _OUTLINE_OFFSCREEN = None
    if _OUTLINE_OFFSCREEN is None:
        _OUTLINE_OFFSCREEN = gpu.types.GPUOffScreen(width, height, format="RGBA8")
        _OUTLINE_OFFSCREEN_SIZE = size
    return _OUTLINE_OFFSCREEN


def _draw_object_outlines(context, view, projection, depsgraph):
    space = context.space_data
    show_outlines = bool(
        space
        and space.overlay.show_overlays
        and getattr(space.overlay, "show_outline_selected", True)
    )
    if context.mode != "OBJECT" or not show_outlines:
        return 0

    selected = [
        obj for obj in context.scene.objects
        if obj.type == "MESH" and obj.select_get() and obj.visible_get()
    ]
    if not selected:
        return 0

    mask_shader = _create_outline_mask_shader()
    composite_shader = _create_outline_composite_shader()
    theme = context.preferences.themes[0].view_3d
    active = context.view_layer.objects.active
    outline_radius = max(
        1,
        min(2, round(float(getattr(theme, "outline_width", 1.0)))),
    )
    offscreen = _outline_offscreen(context.region.width, context.region.height)
    quad = batch_for_shader(
        composite_shader,
        "TRI_FAN",
        {
            "position": ((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)),
            "uv": ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
        },
    )
    used_keys = set()
    mask_triangles = 0

    for obj in selected:
        evaluated = obj.evaluated_get(depsgraph)
        with offscreen.bind():
            framebuffer = gpu.state.active_framebuffer_get()
            framebuffer.clear(color=(0.0, 0.0, 0.0, 0.0), depth=1.0)
            gpu.state.blend_set("NONE")
            gpu.state.depth_test_set("LESS_EQUAL")
            gpu.state.depth_mask_set(True)
            mask_shader.bind()
            mask_shader.uniform_float(
                "mvp", projection @ view @ evaluated.matrix_world
            )
            for material_index in range(max(1, len(obj.material_slots))):
                data = _geometry(obj, material_index, depsgraph)
                if data is None:
                    continue
                key = (obj.as_pointer(), material_index)
                used_keys.add(key)
                _outline_mask_batch(mask_shader, key, data).draw(mask_shader)
                mask_triangles += len(data["position"]) // 3

        gpu.state.depth_test_set("NONE")
        gpu.state.depth_mask_set(False)
        gpu.state.blend_set("ALPHA")
        composite_shader.bind()
        composite_shader.uniform_sampler("maskTexture", offscreen.texture_color)
        composite_shader.uniform_int("outlineRadius", outline_radius)
        color = theme.object_active if obj == active else theme.object_selected
        composite_shader.uniform_float("outlineColor", (*color[:], 1.0))
        quad.draw(composite_shader)

    gpu.state.blend_set("NONE")
    for key in [key for key in _GPU_OUTLINE_MASKS if key not in used_keys]:
        del _GPU_OUTLINE_MASKS[key]
    return mask_triangles


def _draw():
    global _LAST_ERROR, _DRAW_COUNT, _LAST_TRIANGLES, _LAST_TIMINGS
    context = bpy.context
    if context.area is None or context.area.type != "VIEW_3D":
        return
    region_data = context.region_data
    if region_data is None:
        return

    shader = None
    try:
        frame_start = time.perf_counter()
        _LAST_ERROR = ""
        _DRAW_COUNT += 1
        _LAST_TRIANGLES = 0
        shader_start = time.perf_counter()
        shader = _create_shader()
        shader_end = time.perf_counter()
        framebuffer = gpu.state.active_framebuffer_get()
        framebuffer.clear(color=(0.107, 0.107, 0.107, 1.0), depth=1.0)
        gpu.state.depth_test_set("LESS_EQUAL")
        gpu.state.depth_mask_set(True)
        gpu.state.face_culling_set("NONE")
        shader.bind()
        shader.uniform_float("diffuseLevel", _PARAMS["diffuse"])
        shader.uniform_float("specularLevel", _PARAMS["specular"])
        shader.uniform_float("blinnExponent", _PARAMS["exponent"])
        shader.uniform_float("fillLevel", _PARAMS["fill"])
        shader.uniform_float("lightX", _PARAMS["light_x"])
        shader.uniform_float("lightY", _PARAMS["light_y"])
        shader.uniform_int("aoEnabled", 0)
        shader.uniform_int("aoOnly", _PARAMS["ao_only"])
        shader.uniform_int("useAo", _PARAMS["use_ao"])
        shader.uniform_int("defaultMaterial", _PARAMS["default_material"])
        shader.uniform_int("isPerspective", int(region_data.is_perspective))
        shader.uniform_int("directXNormal", _PARAMS["directx_normal"])
        shader.uniform_int("alphaEnabled", 0)
        shader.uniform_int("alphaChannel", 0)
        shader.uniform_int("alphaClip", 0)
        shader.uniform_float("materialAlpha", 1.0)

        view = region_data.view_matrix
        projection = region_data.window_matrix
        depsgraph = context.evaluated_depsgraph_get()
        geometry_time = 0.0
        upload_time = 0.0
        draw_time = 0.0
        used_geometry_keys = set()
        opaque_items = []
        transparent_items = []
        for obj in context.scene.objects:
            if obj.type != "MESH" or not obj.visible_get():
                continue
            evaluated_obj = obj.evaluated_get(depsgraph)
            model_view = view @ evaluated_obj.matrix_world
            normal_matrix = Matrix(model_view.to_3x3()).inverted().transposed()
            mvp = projection @ model_view
            sort_depth = model_view.translation.z
            for material_index in range(max(1, len(obj.material_slots))):
                material = obj.material_slots[material_index].material if obj.material_slots else None
                image = _normal_image(material)
                ao_image = _ao_image(material)
                alpha_image, alpha_channel, material_alpha = _alpha_settings(
                    material
                )
                part_start = time.perf_counter()
                data = _geometry(obj, material_index, depsgraph)
                geometry_time += time.perf_counter() - part_start
                if data is None:
                    continue
                part_start = time.perf_counter()
                key = (obj.as_pointer(), material_index)
                batch, uploaded = _geometry_batch(shader, key, data)
                used_geometry_keys.add(key)
                if uploaded:
                    upload_time += time.perf_counter() - part_start
                _LAST_TRIANGLES += len(data["position"]) // 3
                item = (
                    sort_depth, batch, model_view, normal_matrix, mvp,
                    image, ao_image, alpha_image, alpha_channel,
                    material_alpha,
                )
                is_transparent = (
                    not _PARAMS["default_material"]
                    and alpha_image is None
                    and material_alpha < 0.999
                )
                (transparent_items if is_transparent else opaque_items).append(item)

        def draw_items(items):
            nonlocal draw_time
            for (
                _sort_depth, batch, model_view, normal_matrix, mvp,
                image, ao_image, alpha_image, alpha_channel,
                material_alpha,
            ) in items:
                shader.uniform_float("modelView", model_view)
                shader.uniform_float("normalMatrix", normal_matrix)
                shader.uniform_float("mvp", mvp)
                texture = _gpu_texture(image, (0.5, 0.5, 1.0, 1.0))
                ao_texture = _gpu_texture(ao_image, (1.0, 1.0, 1.0, 1.0))
                alpha_texture = _gpu_texture(
                    alpha_image, (1.0, 1.0, 1.0, 1.0)
                )
                shader.uniform_sampler("normalTexture", texture)
                shader.uniform_sampler("aoTexture", ao_texture)
                shader.uniform_sampler("alphaTexture", alpha_texture)
                shader.uniform_int("aoEnabled", int(ao_image is not None))
                shader.uniform_int("alphaEnabled", int(alpha_image is not None))
                shader.uniform_int("alphaChannel", alpha_channel)
                shader.uniform_int("alphaClip", int(alpha_image is not None))
                shader.uniform_float("materialAlpha", material_alpha)
                part_start = time.perf_counter()
                batch.draw(shader)
                draw_time += time.perf_counter() - part_start
                del alpha_texture
                del ao_texture
                del texture

        gpu.state.blend_set("NONE")
        gpu.state.depth_mask_set(True)
        draw_items(opaque_items)
        if transparent_items:
            gpu.state.blend_set("ALPHA")
            gpu.state.depth_mask_set(False)
            draw_items(sorted(transparent_items, key=lambda item: item[0]))
            gpu.state.blend_set("NONE")
        for key in [key for key in _GPU_GEOMETRY if key not in used_geometry_keys]:
            del _GPU_GEOMETRY[key]
        outline_start = time.perf_counter()
        outline_triangles = _draw_object_outlines(
            context, view, projection, depsgraph
        )
        outline_time = time.perf_counter() - outline_start
        overlay_start = time.perf_counter()
        overlay_elements, overlay_rebuild = _draw_edit_overlays(
            context, view, projection, depsgraph
        )
        overlay_time = time.perf_counter() - overlay_start
        _LAST_TIMINGS = {
            "shader_ms": (shader_end - shader_start) * 1000.0,
            "geometry_ms": geometry_time * 1000.0,
            "upload_ms": upload_time * 1000.0,
            "draw_ms": draw_time * 1000.0,
            "outline_ms": outline_time * 1000.0,
            "outline_triangles": outline_triangles,
            "overlay_ms": overlay_time * 1000.0,
            "overlay_rebuild_ms": overlay_rebuild * 1000.0,
            "overlay_elements": overlay_elements,
            "frame_ms": (time.perf_counter() - frame_start) * 1000.0,
        }

    except Exception as error:
        _LAST_ERROR = "%s: %s" % (type(error).__name__, error)
    finally:
        gpu.state.face_culling_set("NONE")
        gpu.state.blend_set("NONE")
        gpu.state.depth_mask_set(False)
        gpu.state.depth_test_set("NONE")
        if shader is not None:
            del shader


def enable(context):
    global _HANDLER
    if _HANDLER is not None:
        return
    state.capture(context)
    context.scene["mvm_match_mode"] = "CUSTOM_GPU"
    for obj in context.scene.objects:
        if obj.type == "MESH" and obj.data.is_editmode:
            obj.update_from_editmode()
    depsgraph = context.evaluated_depsgraph_get()
    _remove_depsgraph_handlers()
    bpy.app.handlers.depsgraph_update_post.append(_depsgraph_geometry_update)
    for obj in context.scene.objects:
        if obj.type != "MESH":
            continue
        for material_index in range(max(1, len(obj.material_slots))):
            _geometry(obj, material_index, depsgraph)
    _HANDLER = bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_VIEW")
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.shading.type = "SOLID"
                area.tag_redraw()


def disable():
    global _HANDLER, _OUTLINE_OFFSCREEN, _OUTLINE_OFFSCREEN_SIZE
    if _HANDLER is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_HANDLER, "WINDOW")
        _HANDLER = None
    _CPU_GEOMETRY.clear()
    _GPU_GEOMETRY.clear()
    _GPU_OUTLINE_MASKS.clear()
    if _OUTLINE_OFFSCREEN is not None:
        _OUTLINE_OFFSCREEN.free()
        _OUTLINE_OFFSCREEN = None
        _OUTLINE_OFFSCREEN_SIZE = None
    _EDIT_OVERLAY_BATCHES.clear()
    _EDIT_OVERLAY_DIRTY.clear()
    _EDIT_DIRTY.clear()
    _EDIT_SYNC_SKIP.clear()
    _EDIT_TOPOLOGY.clear()
    _remove_depsgraph_handlers()
    _PARAMS["ao_only"] = 0
    _PARAMS["use_ao"] = 1
    _PARAMS["default_material"] = 0
    _PARAMS["directx_normal"] = 0


def is_enabled():
    return _HANDLER is not None


def last_error():
    return _LAST_ERROR


def set_display_mode(mode):
    modes = {
        "NORMAL_ONLY": (0, 0, 0),
        "NORMAL_AO": (0, 1, 0),
        "AO_ONLY": (1, 1, 0),
        "DEFAULT_MATERIAL": (0, 0, 1),
    }
    if mode not in modes:
        raise ValueError("Unknown custom viewport mode: %s" % mode)
    (_PARAMS["ao_only"], _PARAMS["use_ao"],
     _PARAMS["default_material"]) = modes[mode]
    return mode


def display_mode():
    if _PARAMS["ao_only"]:
        return "AO_ONLY"
    if _PARAMS["default_material"]:
        return "DEFAULT_MATERIAL"
    return "NORMAL_AO" if _PARAMS["use_ao"] else "NORMAL_ONLY"


def set_normal_convention(convention):
    conventions = {
        "OPENGL": 0,
        "DIRECTX": 1,
    }
    if convention not in conventions:
        raise ValueError("Unknown normal map convention: %s" % convention)
    _PARAMS["directx_normal"] = conventions[convention]
    return convention


def normal_convention():
    return "DIRECTX" if _PARAMS["directx_normal"] else "OPENGL"


def debug_stats():
    return {
        "draw_count": _DRAW_COUNT,
        "triangles": _LAST_TRIANGLES,
        "cpu_batches": len(_CPU_GEOMETRY),
        "gpu_batches": len(_GPU_GEOMETRY),
        "outline_mask_batches": len(_GPU_OUTLINE_MASKS),
        "overlay_batches": len(_EDIT_OVERLAY_BATCHES),
        "error": _LAST_ERROR,
        "timings": dict(_LAST_TIMINGS),
    }
