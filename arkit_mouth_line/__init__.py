bl_info = {
    "name": "ARKit Mouth Line Binder",
    "author": "OpenAI Codex",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > ARKit Mouth Line",
    "description": "Build a non-destructive single-mesh ARKit export copy from an existing face and mouth line",
    "category": "Animation",
}

import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Operator, Panel, PropertyGroup, UIList
from mathutils import Vector
from mathutils.bvhtree import BVHTree


ADDON_VERSION = "1.0.0"
LENGTH_KEY_NAMES = {
    "LEFT": "mouthLineLengthLeft",
    "RIGHT": "mouthLineLengthRight",
}

MOUTH_KEYS = (
    "jawForward",
    "jawLeft",
    "jawRight",
    "jawOpen",
    "mouthClose",
    "mouthFunnel",
    "mouthPucker",
    "mouthLeft",
    "mouthRight",
    "mouthSmileLeft",
    "mouthSmileRight",
    "mouthFrownLeft",
    "mouthFrownRight",
    "mouthDimpleLeft",
    "mouthDimpleRight",
    "mouthStretchLeft",
    "mouthStretchRight",
    "mouthRollLower",
    "mouthRollUpper",
    "mouthShrugLower",
    "mouthShrugUpper",
    "mouthPressLeft",
    "mouthPressRight",
    "mouthLowerDownLeft",
    "mouthLowerDownRight",
    "mouthUpperUpLeft",
    "mouthUpperUpRight",
    "cheekPuff",
)

SYMMETRIC_MOUTH_KEYS = (
    "jawForward",
    "jawOpen",
    "mouthClose",
    "mouthFunnel",
    "mouthPucker",
    "mouthRollLower",
    "mouthRollUpper",
    "mouthShrugLower",
    "mouthShrugUpper",
    "cheekPuff",
)

MIRRORED_MOUTH_KEY_PAIRS = (
    ("jawLeft", "jawRight"),
    ("mouthLeft", "mouthRight"),
    ("mouthSmileLeft", "mouthSmileRight"),
    ("mouthFrownLeft", "mouthFrownRight"),
    ("mouthDimpleLeft", "mouthDimpleRight"),
    ("mouthStretchLeft", "mouthStretchRight"),
    ("mouthPressLeft", "mouthPressRight"),
    ("mouthLowerDownLeft", "mouthLowerDownRight"),
    ("mouthUpperUpLeft", "mouthUpperUpRight"),
)

LEFT_CORNER_KEYS = (
    "mouthSmileLeft",
    "mouthFrownLeft",
    "mouthDimpleLeft",
    "mouthStretchLeft",
)

RIGHT_CORNER_KEYS = (
    "mouthSmileRight",
    "mouthFrownRight",
    "mouthDimpleRight",
    "mouthStretchRight",
)

BIND_ATTRIBUTES = {
    "aml_v0": "INT",
    "aml_v1": "INT",
    "aml_v2": "INT",
    "aml_w0": "FLOAT",
    "aml_w1": "FLOAT",
    "aml_w2": "FLOAT",
    "aml_ox": "FLOAT",
    "aml_oy": "FLOAT",
    "aml_oz": "FLOAT",
}


def _normalise_name(name):
    return "".join(char.lower() for char in name if char.isalnum())


def _mesh_object_poll(_self, obj):
    return obj is not None and obj.type == "MESH"


def _shape_key_map(obj):
    if obj is None or obj.type != "MESH" or obj.data.shape_keys is None:
        return {}
    return {_normalise_name(block.name): block for block in obj.data.shape_keys.key_blocks}


def _get_shape_key(obj, canonical_name):
    return _shape_key_map(obj).get(_normalise_name(canonical_name))


def _basis_coords(obj):
    keys = obj.data.shape_keys
    if keys is not None and keys.reference_key is not None:
        return [point.co.copy() for point in keys.reference_key.data]
    return [vertex.co.copy() for vertex in obj.data.vertices]


def _key_target_coords(obj, key_block):
    """Return the absolute target coordinates for one relative shape key."""
    keys = obj.data.shape_keys
    basis = keys.reference_key
    if key_block == basis:
        return [point.co.copy() for point in basis.data]

    relative = key_block.relative_key or basis
    if relative == basis:
        return [point.co.copy() for point in key_block.data]

    return [
        basis.data[index].co + key_block.data[index].co - relative.data[index].co
        for index in range(len(basis.data))
    ]


def _build_surface(obj, coords=None):
    mesh = obj.data
    mesh.calc_loop_triangles()
    triangles = [tuple(loop_tri.vertices) for loop_tri in mesh.loop_triangles]
    vertices = coords if coords is not None else _basis_coords(obj)
    if not triangles:
        raise RuntimeError("面部模型没有可用于绑定的三角形。")
    tree = BVHTree.FromPolygons(vertices, triangles, all_triangles=True)
    return vertices, triangles, tree


def _barycentric(point, a, b, c):
    v0 = b - a
    v1 = c - a
    v2 = point - a
    d00 = v0.dot(v0)
    d01 = v0.dot(v1)
    d11 = v1.dot(v1)
    d20 = v2.dot(v0)
    d21 = v2.dot(v1)
    denominator = d00 * d11 - d01 * d01
    if abs(denominator) < 1.0e-16:
        return (1.0, 0.0, 0.0)
    w1 = (d11 * d20 - d01 * d21) / denominator
    w2 = (d00 * d21 - d01 * d20) / denominator
    w0 = 1.0 - w1 - w2
    total = w0 + w1 + w2
    if abs(total) < 1.0e-12:
        return (1.0, 0.0, 0.0)
    return (w0 / total, w1 / total, w2 / total)


def _triangle_frame(a, b, c):
    tangent = b - a
    normal = tangent.cross(c - a)
    if tangent.length_squared < 1.0e-16 or normal.length_squared < 1.0e-16:
        return Vector((1.0, 0.0, 0.0)), Vector((0.0, 1.0, 0.0)), Vector((0.0, 0.0, 1.0))
    tangent.normalize()
    normal.normalize()
    bitangent = normal.cross(tangent)
    bitangent.normalize()
    return tangent, bitangent, normal


def _line_points_in_face_space(face_obj, line_obj):
    transform = face_obj.matrix_world.inverted_safe() @ line_obj.matrix_world
    return [transform @ vertex.co for vertex in line_obj.data.vertices]


def _farthest_axis(points):
    if len(points) < 2:
        raise RuntimeError("Line 至少需要两个顶点。")
    best_i = 0
    best_j = 1
    best_distance = -1.0
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            distance = (points[i] - points[j]).length_squared
            if distance > best_distance:
                best_distance = distance
                best_i = i
                best_j = j
    axis = points[best_j] - points[best_i]
    if axis.length_squared < 1.0e-16:
        raise RuntimeError("Line 的尺寸为零，无法检测两端。")
    axis.normalize()
    projections = [point.dot(axis) for point in points]
    low = min(projections)
    high = max(projections)
    span = high - low
    threshold = max(span * 0.14, 1.0e-8)
    low_points = [point for point, value in zip(points, projections) if value <= low + threshold]
    high_points = [point for point, value in zip(points, projections) if value >= high - threshold]
    end_a = sum(low_points, Vector()) / len(low_points)
    end_b = sum(high_points, Vector()) / len(high_points)
    return end_a, end_b, axis, span, projections


def _corner_target(face_obj, base_coords, key_names):
    key_blocks = [block for name in key_names if (block := _get_shape_key(face_obj, name)) is not None]
    if not key_blocks:
        return None, 0.0

    candidates = []
    for index, position in enumerate(base_coords):
        influence = 0.0
        votes = 0
        for block in key_blocks:
            delta = (block.data[index].co - base_coords[index]).length
            influence += delta
            votes += int(delta > 1.0e-7)
        if influence <= 1.0e-9:
            continue
        candidates.append((influence * (1.0 + votes * 0.2), position))

    if not candidates:
        return None, 0.0

    candidates.sort(key=lambda item: item[0], reverse=True)
    selected = candidates[: min(16, len(candidates))]
    weight_sum = sum(score for score, _position in selected)
    target = sum((position * score for score, position in selected), Vector()) / weight_sum
    confidence = selected[0][0] / max(weight_sum / len(selected), 1.0e-12)
    return target, confidence


def _selected_corner_target(face_obj, line_obj, follow_side):
    base_coords, _triangles, tree = _build_surface(face_obj)
    points = _line_points_in_face_space(face_obj, line_obj)
    centre = sum(points, Vector()) / len(points)

    fallback = tree.find_nearest(centre)
    surface_anchor = fallback[0] if fallback and fallback[0] is not None else centre
    side = follow_side.upper()
    if side == "LEFT":
        target, confidence = _corner_target(face_obj, base_coords, LEFT_CORNER_KEYS)
        label = "Left"
    elif side == "RIGHT":
        target, confidence = _corner_target(face_obj, base_coords, RIGHT_CORNER_KEYS)
        label = "Right"
    else:
        raise RuntimeError("嘴角跟随方向必须是 Left 或 Right。")
    if target is None:
        raise RuntimeError(f"无法从 ARKit Shape Keys 中识别 {label} 嘴角。")
    return surface_anchor, target, confidence, label


def _detect_source_side(face_obj, line_obj):
    """Detect which semantic ARKit mouth corner is closest to the authored Line."""
    base_coords = _basis_coords(face_obj)
    left_target, left_confidence = _corner_target(face_obj, base_coords, LEFT_CORNER_KEYS)
    right_target, right_confidence = _corner_target(face_obj, base_coords, RIGHT_CORNER_KEYS)
    if left_target is None or right_target is None:
        raise RuntimeError("无法同时识别左右 ARKit 嘴角，不能自动判断或镜像 Line。")

    points = _line_points_in_face_space(face_obj, line_obj)
    centre = sum(points, Vector()) / len(points)
    left_distance = (centre - left_target).length
    right_distance = (centre - right_target).length
    mouth_width = (right_target - left_target).length
    if mouth_width < 1.0e-8:
        raise RuntimeError("左右嘴角位置重合，无法建立面部对称平面。")

    margin = abs(left_distance - right_distance) / mouth_width
    if margin < 0.08:
        raise RuntimeError("Line 太靠近嘴部中心，无法可靠判断左右；请把月牙放在正确的一侧。")
    if left_distance < right_distance:
        source_side, mirror_side = "LEFT", "RIGHT"
        source_label, mirror_label = "Left", "Right"
    else:
        source_side, mirror_side = "RIGHT", "LEFT"
        source_label, mirror_label = "Right", "Left"
    return {
        "source_side": source_side,
        "mirror_side": mirror_side,
        "source_label": source_label,
        "mirror_label": mirror_label,
        "left_target": left_target,
        "right_target": right_target,
        "margin": margin,
        "left_confidence": left_confidence,
        "right_confidence": right_confidence,
    }


def _create_mirrored_line(face_obj, source_line, side_info, object_name):
    """Create a temporary reflection across the ARKit mouth-centre symmetry plane."""
    mirror = source_line.copy()
    mirror.data = source_line.data.copy()
    mirror.name = object_name
    mirror.data.name = f"{object_name}_Mesh"
    _link_copy_to_source_collection(face_obj, mirror)

    plane_point = (side_info["left_target"] + side_info["right_target"]) * 0.5
    plane_normal = side_info["right_target"] - side_info["left_target"]
    plane_normal.normalize()
    points = _line_points_in_face_space(face_obj, source_line)
    reflected = [
        point - plane_normal * (2.0 * (point - plane_point).dot(plane_normal))
        for point in points
    ]
    face_to_mirror = mirror.matrix_world.inverted_safe() @ face_obj.matrix_world
    for vertex, point in zip(mirror.data.vertices, reflected):
        vertex.co = face_to_mirror @ point
    mirror.data.flip_normals()
    mirror.data.update()
    return mirror


def _surface_binding_at_point(face_obj, target, confidence, side):
    base_coords, triangles, tree = _build_surface(face_obj)
    nearest = tree.find_nearest(target)
    if nearest is None or nearest[0] is None or nearest[2] is None:
        raise RuntimeError("无法把嘴角锚点绑定到面部表面。")
    location, _normal, triangle_index, _distance = nearest
    v0, v1, v2 = triangles[triangle_index]
    a, b, c = base_coords[v0], base_coords[v1], base_coords[v2]
    weights = _barycentric(location, a, b, c)
    return {
        "vertex_ids": (v0, v1, v2),
        "weights": weights,
        "anchor": a * weights[0] + b * weights[1] + c * weights[2],
        "confidence": confidence,
        "side": side,
    }


def _corner_surface_binding(face_obj, line_obj, follow_side):
    _surface_anchor, semantic_corner, confidence, side = _selected_corner_target(
        face_obj,
        line_obj,
        follow_side,
    )
    return _surface_binding_at_point(face_obj, semantic_corner, confidence, side)


def _mirrored_corner_surface_binding(face_obj, source_binding, side_info):
    """Bind the second crescent at the reflection of the source anchor.

    Detecting both sides independently can select non-homologous triangles.  A
    reflected source anchor keeps the pair spatially corresponding before the
    per-key translation correction is applied.
    """
    plane_point = (side_info["left_target"] + side_info["right_target"]) * 0.5
    plane_normal = side_info["right_target"] - side_info["left_target"]
    plane_normal.normalize()
    source_anchor = source_binding["anchor"]
    target = source_anchor - plane_normal * (
        2.0 * (source_anchor - plane_point).dot(plane_normal)
    )
    mirror_side = side_info["mirror_side"]
    confidence = (
        side_info["left_confidence"]
        if mirror_side == "LEFT"
        else side_info["right_confidence"]
    )
    return _surface_binding_at_point(face_obj, target, confidence, side_info["mirror_label"])


def _evaluate_corner_binding(binding, coords):
    v0, v1, v2 = binding["vertex_ids"]
    w0, w1, w2 = binding["weights"]
    a, b, c = coords[v0], coords[v1], coords[v2]
    return a * w0 + b * w1 + c * w2


def _line_root_pivot(points, corner_anchor):
    """Find the authored Line cross-section nearest the mouth-corner anchor."""
    _end_a, _end_b, axis, _span, projections = _farthest_axis(points)
    anchor_projection = corner_anchor.dot(axis)
    ring_size = min(len(points), max(4, int(round(len(points) / 9.0))))
    root_indices = sorted(
        range(len(points)),
        key=lambda index: abs(projections[index] - anchor_projection),
    )[:ring_size]
    return sum((points[index] for index in root_indices), Vector()) / len(root_indices)


def _ensure_attribute(mesh, name, data_type):
    attribute = mesh.attributes.get(name)
    if attribute is not None and (attribute.data_type != data_type or attribute.domain != "POINT"):
        mesh.attributes.remove(attribute)
        attribute = None
    if attribute is None:
        attribute = mesh.attributes.new(name=name, type=data_type, domain="POINT")
    return attribute


def _write_attribute(mesh, name, values):
    attribute = _ensure_attribute(mesh, name, BIND_ATTRIBUTES[name])
    for item, value in zip(attribute.data, values):
        item.value = value


def _read_attribute(mesh, name):
    attribute = mesh.attributes.get(name)
    if attribute is None or len(attribute.data) != len(mesh.vertices):
        raise RuntimeError("Line 的绑定数据缺失，请重新执行“拟合、绑定并生成”。")
    return [item.value for item in attribute.data]


def _bind_line(face_obj, line_obj):
    base_coords, triangles, tree = _build_surface(face_obj)
    points = _line_points_in_face_space(face_obj, line_obj)
    values = {name: [] for name in BIND_ATTRIBUTES}

    for point in points:
        nearest = tree.find_nearest(point)
        if nearest is None or nearest[0] is None or nearest[2] is None:
            raise RuntimeError("无法将 Line 顶点投射到面部表面。")
        location, _normal, triangle_index, _distance = nearest
        v0, v1, v2 = triangles[triangle_index]
        a, b, c = base_coords[v0], base_coords[v1], base_coords[v2]
        w0, w1, w2 = _barycentric(location, a, b, c)
        surface = a * w0 + b * w1 + c * w2
        tangent, bitangent, normal = _triangle_frame(a, b, c)
        offset = point - surface

        values["aml_v0"].append(v0)
        values["aml_v1"].append(v1)
        values["aml_v2"].append(v2)
        values["aml_w0"].append(w0)
        values["aml_w1"].append(w1)
        values["aml_w2"].append(w2)
        values["aml_ox"].append(offset.dot(tangent))
        values["aml_oy"].append(offset.dot(bitangent))
        values["aml_oz"].append(offset.dot(normal))

    for name, attribute_values in values.items():
        _write_attribute(line_obj.data, name, attribute_values)

    line_obj["aml_bound_face"] = face_obj.name
    line_obj["aml_face_vertex_count"] = len(face_obj.data.vertices)
    line_obj["aml_line_vertex_count"] = len(line_obj.data.vertices)
    line_obj["aml_version"] = ADDON_VERSION
    return values


def _binding_values(line_obj):
    return {name: _read_attribute(line_obj.data, name) for name in BIND_ATTRIBUTES}


def _sample_bound_positions_face_space(line_obj, face_coords, binding):
    positions = []
    normals = []
    count = len(line_obj.data.vertices)
    for index in range(count):
        v0 = int(binding["aml_v0"][index])
        v1 = int(binding["aml_v1"][index])
        v2 = int(binding["aml_v2"][index])
        w0 = binding["aml_w0"][index]
        w1 = binding["aml_w1"][index]
        w2 = binding["aml_w2"][index]
        a, b, c = face_coords[v0], face_coords[v1], face_coords[v2]
        surface = a * w0 + b * w1 + c * w2
        tangent, bitangent, normal = _triangle_frame(a, b, c)
        point = (
            surface
            + tangent * binding["aml_ox"][index]
            + bitangent * binding["aml_oy"][index]
            + normal * binding["aml_oz"][index]
        )
        positions.append(point)
        normals.append(normal)
    return positions, normals


def _copy_armature_weights(face_obj, line_obj, corner_binding):
    """Give every Line vertex the same interpolated corner weights to avoid skinning stretch."""
    source_groups = {group.index: group.name for group in face_obj.vertex_groups}
    if not source_groups:
        return 0

    for group in list(line_obj.vertex_groups):
        line_obj.vertex_groups.remove(group)
    target_groups = {name: line_obj.vertex_groups.new(name=name) for name in source_groups.values()}

    combined = {}
    for face_index, bary_weight in zip(corner_binding["vertex_ids"], corner_binding["weights"]):
        for membership in face_obj.data.vertices[face_index].groups:
            group_name = source_groups.get(membership.group)
            if group_name is not None:
                combined[group_name] = combined.get(group_name, 0.0) + bary_weight * membership.weight
    total = sum(value for value in combined.values() if value > 1.0e-8)
    if total <= 1.0e-8:
        return 0

    all_vertices = list(range(len(line_obj.data.vertices)))
    for group_name, value in combined.items():
        if value > 1.0e-8:
            target_groups[group_name].add(all_vertices, value / total, "REPLACE")
    return len(all_vertices)


def _compute_translated_line_targets(face_obj, line_obj, corner_binding):
    """Apply one mouth-corner translation to every Line vertex for every shape key.

    Translation-only deltas remain perfectly shape-preserving not just at a key's
    endpoint, but also at intermediate values and when mocap blends several ARKit
    keys at once. Interpolating rotations through relative shape keys would scale
    or shear the Line, so rotation is intentionally excluded here.
    """
    basis_line = _line_points_in_face_space(face_obj, line_obj)
    basis_anchor = corner_binding["anchor"]
    mouth_names = {_normalise_name(name): name for name in MOUTH_KEYS}
    targets = {}

    for source_block in face_obj.data.shape_keys.key_blocks[1:]:
        canonical = mouth_names.get(_normalise_name(source_block.name))
        if canonical is None:
            targets[source_block.name] = [point.copy() for point in basis_line]
            continue
        face_coords = _key_target_coords(face_obj, source_block)
        target_anchor = _evaluate_corner_binding(corner_binding, face_coords)
        translation = target_anchor - basis_anchor
        targets[source_block.name] = [point + translation for point in basis_line]

    return basis_line, targets


def _reflect_vector(vector, plane_normal):
    return vector - plane_normal * (2.0 * vector.dot(plane_normal))


def _symmetrise_line_targets(face_obj, side_bases, side_targets, plane_normal):
    """Make paired mouth-line translations exact mirrors without deforming either line.

    Bilateral keys receive the average of the measured left motion and the
    reflected right motion.  Left/Right key pairs are corrected across their
    counterpart keys, so a unilateral key remains unilateral while equal pair
    weights produce an exactly symmetric result.
    """
    translations = {"LEFT": {}, "RIGHT": {}}
    for side in ("LEFT", "RIGHT"):
        basis = side_bases[side]
        for key_name, positions in side_targets[side].items():
            if basis and positions:
                translations[side][key_name] = positions[0] - basis[0]

    def actual_name(canonical_name):
        block = _get_shape_key(face_obj, canonical_name)
        return block.name if block is not None else None

    for canonical_name in SYMMETRIC_MOUTH_KEYS:
        key_name = actual_name(canonical_name)
        if (
            key_name is None
            or key_name not in translations["LEFT"]
            or key_name not in translations["RIGHT"]
        ):
            continue
        left_motion = translations["LEFT"][key_name]
        right_motion = translations["RIGHT"][key_name]
        corrected_left = (left_motion + _reflect_vector(right_motion, plane_normal)) * 0.5
        translations["LEFT"][key_name] = corrected_left
        translations["RIGHT"][key_name] = _reflect_vector(corrected_left, plane_normal)

    for canonical_left, canonical_right in MIRRORED_MOUTH_KEY_PAIRS:
        left_name = actual_name(canonical_left)
        right_name = actual_name(canonical_right)
        if left_name is None or right_name is None:
            continue
        required = (
            left_name in translations["LEFT"]
            and left_name in translations["RIGHT"]
            and right_name in translations["LEFT"]
            and right_name in translations["RIGHT"]
        )
        if not required:
            continue

        left_key_left_motion = translations["LEFT"][left_name]
        right_key_right_motion = translations["RIGHT"][right_name]
        corrected_left_active = (
            left_key_left_motion
            + _reflect_vector(right_key_right_motion, plane_normal)
        ) * 0.5
        translations["LEFT"][left_name] = corrected_left_active
        translations["RIGHT"][right_name] = _reflect_vector(
            corrected_left_active,
            plane_normal,
        )

        left_key_right_motion = translations["RIGHT"][left_name]
        right_key_left_motion = translations["LEFT"][right_name]
        corrected_right_in_left_key = (
            left_key_right_motion
            + _reflect_vector(right_key_left_motion, plane_normal)
        ) * 0.5
        translations["RIGHT"][left_name] = corrected_right_in_left_key
        translations["LEFT"][right_name] = _reflect_vector(
            corrected_right_in_left_key,
            plane_normal,
        )

    corrected_targets = {"LEFT": {}, "RIGHT": {}}
    for side in ("LEFT", "RIGHT"):
        basis = side_bases[side]
        for key_name, positions in side_targets[side].items():
            motion = translations[side].get(key_name)
            if motion is None:
                corrected_targets[side][key_name] = [point.copy() for point in positions]
            else:
                corrected_targets[side][key_name] = [point + motion for point in basis]
    return corrected_targets


def _link_copy_to_source_collection(source_obj, copy_obj):
    collection = source_obj.users_collection[0] if source_obj.users_collection else bpy.context.scene.collection
    collection.objects.link(copy_obj)


def _remove_generated_output(name):
    existing = bpy.data.objects.get(name)
    if existing is None:
        return
    if not existing.get("aml_generated_output"):
        raise RuntimeError(f"对象“{name}”已经存在，但不是本插件生成的对象。请修改输出名称。")
    mesh = existing.data
    bpy.data.objects.remove(existing, do_unlink=True)
    if mesh is not None and mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def _build_export_copy(face_obj, line_obj, settings):
    """Build one symmetric pair from one authored crescent without changing either source."""
    temporary_name = "__AML_BUILD_OUTPUT__"
    temporary_line_name = "__AML_BUILD_LINE__"
    temporary_mirror_name = "__AML_BUILD_MIRROR__"
    for temp_name in (temporary_name, temporary_line_name, temporary_mirror_name):
        existing_temp = bpy.data.objects.get(temp_name)
        if existing_temp is not None:
            temp_mesh = existing_temp.data
            bpy.data.objects.remove(existing_temp, do_unlink=True)
            if temp_mesh is not None and temp_mesh.users == 0:
                bpy.data.meshes.remove(temp_mesh)

    body_copy = face_obj.copy()
    body_copy.data = face_obj.data.copy()
    body_copy.name = temporary_name
    body_copy.data.name = f"{temporary_name}_Mesh"
    _link_copy_to_source_collection(face_obj, body_copy)

    line_copy = line_obj.copy()
    line_copy.data = line_obj.data.copy()
    line_copy.name = temporary_line_name
    line_copy.data.name = "__AML_BUILD_LINE_Mesh"
    _link_copy_to_source_collection(face_obj, line_copy)

    body_vertex_count = len(face_obj.data.vertices)
    line_vertex_count = len(line_obj.data.vertices)
    total_line_vertex_count = line_vertex_count * 2
    original_selected = list(bpy.context.selected_objects)
    original_active = bpy.context.view_layer.objects.active

    try:
        side_info = _detect_source_side(face_obj, line_copy)
        mirror_copy = _create_mirrored_line(
            face_obj,
            line_copy,
            side_info,
            temporary_mirror_name,
        )

        source_binding = _corner_surface_binding(face_obj, line_copy, side_info["source_side"])
        mirror_binding = _mirrored_corner_surface_binding(face_obj, source_binding, side_info)
        weighted_source = _copy_armature_weights(face_obj, line_copy, source_binding)
        weighted_mirror = _copy_armature_weights(face_obj, mirror_copy, mirror_binding)
        weighted = weighted_source + weighted_mirror

        source_basis, source_targets = _compute_translated_line_targets(
            face_obj,
            line_copy,
            source_binding,
        )
        mirror_basis, mirror_targets = _compute_translated_line_targets(
            face_obj,
            mirror_copy,
            mirror_binding,
        )
        plane_normal = side_info["right_target"] - side_info["left_target"]
        plane_normal.normalize()
        side_bases = {
            side_info["source_side"]: source_basis,
            side_info["mirror_side"]: mirror_basis,
        }
        side_targets = {
            side_info["source_side"]: source_targets,
            side_info["mirror_side"]: mirror_targets,
        }
        corrected_targets = _symmetrise_line_targets(
            face_obj,
            side_bases,
            side_targets,
            plane_normal,
        )
        source_targets = corrected_targets[side_info["source_side"]]
        mirror_targets = corrected_targets[side_info["mirror_side"]]
        source_pivot = _line_root_pivot(source_basis, source_binding["anchor"])
        mirror_pivot = _line_root_pivot(mirror_basis, mirror_binding["anchor"])
        source_collapsed = [source_pivot.copy() for _index in range(line_vertex_count)]
        mirror_collapsed = [mirror_pivot.copy() for _index in range(line_vertex_count)]

        for component in (line_copy, mirror_copy):
            bpy.ops.object.select_all(action="DESELECT")
            body_copy.select_set(True)
            component.select_set(True)
            bpy.context.view_layer.objects.active = body_copy
            join_result = bpy.ops.object.join()
            if "FINISHED" not in join_result:
                raise RuntimeError("Blender 无法合并 Body 和对称嘴线副本。")

        output = bpy.context.view_layer.objects.active
        if len(output.data.vertices) != body_vertex_count + total_line_vertex_count:
            raise RuntimeError("合并后的顶点数量不正确。")
        if output.data.shape_keys is None:
            raise RuntimeError("合并时丢失了 ARKit Shape Keys。")

        source_start = body_vertex_count
        source_end = source_start + line_vertex_count
        mirror_start = source_end
        mirror_end = mirror_start + line_vertex_count
        output_keys = output.data.shape_keys
        mouth_names = {_normalise_name(name) for name in MOUTH_KEYS}
        for key_block in list(output_keys.key_blocks):
            if key_block == output_keys.reference_key:
                source_positions = source_collapsed
                mirror_positions = mirror_collapsed
            elif _normalise_name(key_block.name) in mouth_names:
                source_target = source_targets.get(key_block.name, source_basis)
                mirror_target = mirror_targets.get(key_block.name, mirror_basis)
                source_positions = [
                    collapsed + target - full_basis
                    for collapsed, target, full_basis in zip(
                        source_collapsed,
                        source_target,
                        source_basis,
                    )
                ]
                mirror_positions = [
                    collapsed + target - full_basis
                    for collapsed, target, full_basis in zip(
                        mirror_collapsed,
                        mirror_target,
                        mirror_basis,
                    )
                ]
            else:
                source_positions = source_collapsed
                mirror_positions = mirror_collapsed
            for output_index, position in zip(range(source_start, source_end), source_positions):
                key_block.data[output_index].co = position
            for output_index, position in zip(range(mirror_start, mirror_end), mirror_positions):
                key_block.data[output_index].co = position
            if key_block != output_keys.reference_key:
                key_block.value = 0.0

        side_components = {
            side_info["source_side"]: (range(source_start, source_end), source_basis),
            side_info["mirror_side"]: (range(mirror_start, mirror_end), mirror_basis),
        }
        for side, key_name in LENGTH_KEY_NAMES.items():
            if output_keys.key_blocks.get(key_name) is not None:
                raise RuntimeError(f"Body 已经包含名为 {key_name} 的 Shape Key。")
            length_key = output.shape_key_add(name=key_name, from_mix=False)
            for output_index in range(source_start, mirror_end):
                length_key.data[output_index].co = output_keys.reference_key.data[output_index].co
            component_range, component_basis = side_components[side]
            for output_index, position in zip(component_range, component_basis):
                length_key.data[output_index].co = position
            length_key.slider_min = 0.0
            length_key.slider_max = 1.0
            length_key.value = 1.0

        if output_keys.animation_data is not None:
            output_keys.animation_data_clear()
        if output.animation_data is not None:
            output.animation_data_clear()

        _remove_generated_output(settings.output_name)
        output.name = settings.output_name
        output.data.name = f"{settings.output_name}_Mesh"
        output["aml_generated_output"] = True
        output["aml_source_body"] = face_obj.name
        output["aml_source_line"] = line_obj.name
        output["aml_body_vertex_count"] = body_vertex_count
        output["aml_line_vertex_start"] = source_start
        output["aml_line_vertex_count"] = total_line_vertex_count
        output["aml_source_line_vertex_count"] = line_vertex_count
        output["aml_mirror_line_vertex_start"] = mirror_start
        output["aml_mirror_line_vertex_count"] = line_vertex_count
        output["aml_length_key_left"] = LENGTH_KEY_NAMES["LEFT"]
        output["aml_length_key_right"] = LENGTH_KEY_NAMES["RIGHT"]
        output["aml_corner_side"] = side_info["source_label"]
        output["aml_detected_source_side"] = side_info["source_side"]
        output["aml_mirrored_side"] = side_info["mirror_side"]
        output["aml_side_detection_margin"] = side_info["margin"]
        output["aml_symmetric_pair"] = True
        output["aml_symmetry_corrected"] = True
        output["aml_version"] = ADDON_VERSION
        output.data.update()

        bpy.ops.object.select_all(action="DESELECT")
        output.select_set(True)
        bpy.context.view_layer.objects.active = output
        return output, side_info["margin"], weighted, side_info["source_label"]
    except Exception:
        for temp_name in (temporary_mirror_name, temporary_line_name, temporary_name):
            obj = bpy.data.objects.get(temp_name)
            if obj is not None:
                mesh = obj.data
                bpy.data.objects.remove(obj, do_unlink=True)
                if mesh is not None and mesh.users == 0:
                    bpy.data.meshes.remove(mesh)
        bpy.ops.object.select_all(action="DESELECT")
        for obj in original_selected:
            if obj.name in bpy.data.objects:
                obj.select_set(True)
        if original_active is not None and original_active.name in bpy.data.objects:
            bpy.context.view_layer.objects.active = original_active
        raise


def _scan_items(settings):
    settings.keys.clear()
    key_map = _shape_key_map(settings.face_obj)
    found = 0
    for canonical_name in MOUTH_KEYS:
        item = settings.keys.add()
        item.canonical_name = canonical_name
        source_block = key_map.get(_normalise_name(canonical_name))
        item.found = source_block is not None
        item.source_name = source_block.name if source_block is not None else ""
        item.status = "Ready" if source_block is not None else "Missing"
        found += int(source_block is not None)
    return found


def _validate_objects(settings):
    face_obj = settings.face_obj
    line_obj = settings.line_obj
    if face_obj is None or face_obj.type != "MESH":
        raise RuntimeError("请选择包含 ARKit Shape Keys 的面部 Mesh。")
    if line_obj is None or line_obj.type != "MESH":
        raise RuntimeError("请选择当前已有的实体嘴线 Mesh。")
    if face_obj == line_obj:
        raise RuntimeError("Body 和 Line 不能是同一个对象。")
    if face_obj.data.shape_keys is None:
        raise RuntimeError("所选 Body 没有 Shape Keys。")
    if len(line_obj.data.vertices) < 2:
        raise RuntimeError("Line 顶点数量不足。")
    if face_obj.mode != "OBJECT" or line_obj.mode != "OBJECT":
        raise RuntimeError("请先让 Body 和 Line 都处于 Object Mode。")
    return face_obj, line_obj


class AML_KeyItem(PropertyGroup):
    canonical_name: StringProperty(name="ARKit Name")
    source_name: StringProperty(name="Source Name")
    found: BoolProperty(name="Found", default=False)
    status: StringProperty(name="Status")


class AML_Settings(PropertyGroup):
    face_obj: PointerProperty(name="ARKit Face", type=bpy.types.Object, poll=_mesh_object_poll)
    line_obj: PointerProperty(name="Existing Line", type=bpy.types.Object, poll=_mesh_object_poll)
    output_name: StringProperty(name="Output Object", default="Body_ARKit_Line")
    keys: CollectionProperty(type=AML_KeyItem)
    active_key_index: IntProperty(default=0)
    last_message: StringProperty(default="Select the source Body and existing Line, then scan.")


class AML_UL_keys(UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        row = layout.row(align=True)
        row.enabled = item.found
        row.label(text="", icon="CHECKMARK" if item.found else "ERROR")
        row.label(text=item.source_name or item.canonical_name)
        row.label(text=item.status)


class AML_OT_scan_keys(Operator):
    bl_idname = "aml.scan_keys"
    bl_label = "Scan ARKit Mouth Keys"
    bl_description = "Read mouth-related ARKit shape keys from the selected face"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.aml_settings
        try:
            _validate_objects(settings)
            found = _scan_items(settings)
        except RuntimeError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        settings.last_message = f"Found {found}/{len(MOUTH_KEYS)} mouth keys."
        self.report({"INFO"}, settings.last_message)
        return {"FINISHED"}


class AML_OT_reset_position(Operator):
    bl_idname = "aml.reset_position"
    bl_label = "Reset Position Offset"
    bl_description = "Reset the manual surface offset to the authored Line position"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.aml_settings
        settings.position_u = 0.0
        settings.position_v = 0.0
        settings.last_message = "Position offset reset; the authored Line position will be used."
        return {"FINISHED"}


class AML_OT_position_pad(Operator):
    bl_idname = "aml.position_pad"
    bl_label = "Open 2D Position Pad"
    bl_description = "Drag a point in a square pad to move a temporary Line preview along the face; Enter confirms and rebuilds"
    bl_options = {"REGISTER", "UNDO"}

    _draw_handle = None
    _preview_name = "__AML_POSITION_PREVIEW__"
    _dragging = False
    _area = None
    _window_region = None
    _original_u = 0.0
    _original_v = 0.0
    _source_hidden = False
    _pad_size = 220.0
    _pad_margin = 28.0

    def _bounds(self):
        width = self._window_region.width
        height = self._window_region.height
        left = max(self._pad_margin, width - self._pad_size - self._pad_margin)
        bottom = max(self._pad_margin + 40.0, height - self._pad_size - 90.0)
        return left, bottom, self._pad_size, self._pad_size

    def _draw(self):
        if bpy.context.area != self._area or self._window_region is None:
            return
        settings = bpy.context.scene.aml_settings
        left, bottom, width, height = self._bounds()
        right = left + width
        top = bottom + height
        centre_x = left + width * 0.5
        centre_y = bottom + height * 0.5

        gpu.state.blend_set("ALPHA")
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        fill = batch_for_shader(
            shader,
            "TRIS",
            {"pos": [(left, bottom), (right, bottom), (right, top), (left, top)]},
            indices=[(0, 1, 2), (0, 2, 3)],
        )
        shader.bind()
        shader.uniform_float("color", (0.035, 0.035, 0.045, 0.88))
        fill.draw(shader)

        border = batch_for_shader(
            shader,
            "LINE_STRIP",
            {"pos": [(left, bottom), (right, bottom), (right, top), (left, top), (left, bottom)]},
        )
        shader.uniform_float("color", (0.65, 0.72, 0.9, 1.0))
        border.draw(shader)
        cross = batch_for_shader(
            shader,
            "LINES",
            {"pos": [(centre_x, bottom), (centre_x, top), (left, centre_y), (right, centre_y)]},
        )
        shader.uniform_float("color", (0.28, 0.32, 0.42, 0.9))
        cross.draw(shader)

        pad_range = max(settings.pad_range, 1.0e-8)
        norm_x = max(-1.0, min(1.0, settings.position_u / pad_range))
        norm_y = max(-1.0, min(1.0, settings.position_v / pad_range))
        dot_x = centre_x + norm_x * width * 0.5
        dot_y = centre_y + norm_y * height * 0.5
        dot = batch_for_shader(shader, "POINTS", {"pos": [(dot_x, dot_y)]})
        gpu.state.point_size_set(13.0)
        shader.uniform_float("color", (1.0, 0.32, 0.16, 1.0))
        dot.draw(shader)
        gpu.state.point_size_set(1.0)
        gpu.state.blend_set("NONE")

        font_id = 0
        blf.color(font_id, 1.0, 1.0, 1.0, 1.0)
        blf.size(font_id, 14)
        blf.position(font_id, left, top + 14.0, 0)
        blf.draw(font_id, "ARKit Mouth Line — 2D Position")
        blf.size(font_id, 12)
        blf.position(font_id, left, bottom - 22.0, 0)
        blf.draw(font_id, "Drag point • Enter: confirm & rebuild • Esc: cancel")

    def _remove_preview(self):
        preview = bpy.data.objects.get(self._preview_name)
        if preview is not None:
            mesh = preview.data
            bpy.data.objects.remove(preview, do_unlink=True)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)

    def _create_preview(self, face_obj, line_obj):
        self._remove_preview()
        preview = line_obj.copy()
        preview.data = line_obj.data.copy()
        preview.name = self._preview_name
        preview.data.name = f"{self._preview_name}_Mesh"
        _link_copy_to_source_collection(face_obj, preview)
        preview.hide_render = True
        preview.show_in_front = True
        return preview

    def _update_preview(self, context):
        settings = context.scene.aml_settings
        preview = bpy.data.objects.get(self._preview_name)
        if preview is None:
            return
        _apply_position_offset(
            settings.face_obj,
            settings.line_obj,
            preview,
            settings.position_u,
            settings.position_v,
        )
        preview.data.update()
        self._area.tag_redraw()

    def _finish_modal(self, context):
        if self._draw_handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._draw_handle, "WINDOW")
            self._draw_handle = None
        self._remove_preview()
        settings = context.scene.aml_settings
        if settings.line_obj is not None:
            settings.line_obj.hide_set(self._source_hidden)
        if self._area is not None:
            self._area.tag_redraw()

    def _set_from_mouse(self, context, event):
        settings = context.scene.aml_settings
        left, bottom, width, height = self._bounds()
        local_x = event.mouse_x - self._window_region.x
        local_y = event.mouse_y - self._window_region.y
        norm_x = max(-1.0, min(1.0, (local_x - (left + width * 0.5)) / (width * 0.5)))
        norm_y = max(-1.0, min(1.0, (local_y - (bottom + height * 0.5)) / (height * 0.5)))
        settings.position_u = norm_x * settings.pad_range
        settings.position_v = norm_y * settings.pad_range
        self._update_preview(context)

    def invoke(self, context, _event):
        if context.area is None or context.area.type != "VIEW_3D":
            self.report({"ERROR"}, "请从 3D Viewport 的 ARKit Mouth Line 面板启动定位板。")
            return {"CANCELLED"}
        settings = context.scene.aml_settings
        try:
            face_obj, line_obj = _validate_objects(settings)
        except RuntimeError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        self._area = context.area
        self._window_region = next((region for region in context.area.regions if region.type == "WINDOW"), None)
        if self._window_region is None:
            self.report({"ERROR"}, "无法找到 3D Viewport 绘制区域。")
            return {"CANCELLED"}
        self._original_u = settings.position_u
        self._original_v = settings.position_v
        self._source_hidden = line_obj.hide_get()
        line_obj.hide_set(True)
        self._create_preview(face_obj, line_obj)
        self._update_preview(context)
        self._draw_handle = bpy.types.SpaceView3D.draw_handler_add(self._draw, (), "WINDOW", "POST_PIXEL")
        context.window_manager.modal_handler_add(self)
        settings.last_message = "2D pad active: drag the orange point, press Enter to confirm."
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            settings = context.scene.aml_settings
            settings.position_u = self._original_u
            settings.position_v = self._original_v
            settings.last_message = "2D position adjustment cancelled."
            self._finish_modal(context)
            return {"CANCELLED"}

        if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            settings = context.scene.aml_settings
            self._finish_modal(context)
            try:
                face_obj, line_obj = _validate_objects(settings)
                if not settings.keys:
                    _scan_items(settings)
                output, confidence, weighted, corner_side = _build_export_copy(face_obj, line_obj, settings)
            except Exception as error:
                settings.last_message = f"Failed: {error}"
                self.report({"ERROR"}, str(error))
                return {"CANCELLED"}
            settings.last_message = (
                f"Position confirmed; rebuilt {output.name}; {weighted} Line vertices weighted; "
                f"auto source {corner_side}, mirrored pair (margin {confidence:.2f})."
            )
            self.report({"INFO"}, settings.last_message)
            return {"FINISHED"}

        if event.type == "LEFTMOUSE":
            local_x = event.mouse_x - self._window_region.x
            local_y = event.mouse_y - self._window_region.y
            left, bottom, width, height = self._bounds()
            inside = left <= local_x <= left + width and bottom <= local_y <= bottom + height
            if event.value == "PRESS" and inside:
                self._dragging = True
                self._set_from_mouse(context, event)
                return {"RUNNING_MODAL"}
            if event.value == "RELEASE" and self._dragging:
                self._dragging = False
                return {"RUNNING_MODAL"}

        if event.type == "MOUSEMOVE" and self._dragging:
            self._set_from_mouse(context, event)
            return {"RUNNING_MODAL"}

        return {"PASS_THROUGH"}


class AML_OT_build_export_copy(Operator):
    bl_idname = "aml.build_export_copy"
    bl_label = "Build / Rebuild Export Copy"
    bl_description = "Create one non-destructive Body copy directly from the authored Line position"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.aml_settings
        try:
            face_obj, line_obj = _validate_objects(settings)
            if not settings.keys:
                _scan_items(settings)
            output, confidence, weighted, corner_side = _build_export_copy(face_obj, line_obj, settings)
        except Exception as error:
            self.report({"ERROR"}, str(error))
            settings.last_message = f"Failed: {error}"
            return {"CANCELLED"}

        arkit_count = len(face_obj.data.shape_keys.key_blocks) - 1
        settings.last_message = (
            f"Built {output.name}: {arkit_count} ARKit keys + independent Left/Right length; "
            f"weighted {weighted} Line vertices; auto source {corner_side}, "
            f"symmetry-corrected pair (margin {confidence:.2f})."
        )
        self.report({"INFO"}, settings.last_message)
        return {"FINISHED"}


class AML_OT_validate(Operator):
    bl_idname = "aml.validate"
    bl_label = "Validate"
    bl_description = "Check the source objects and the generated single-mesh export copy"

    def execute(self, context):
        settings = context.scene.aml_settings
        try:
            face_obj, line_obj = _validate_objects(settings)
            found = sum(_get_shape_key(face_obj, name) is not None for name in MOUTH_KEYS)
            source_shape_count = len(face_obj.data.shape_keys.key_blocks) - 1
            output = bpy.data.objects.get(settings.output_name)
            if output is None or not output.get("aml_generated_output"):
                raise RuntimeError("尚未生成有效的导出副本。")
            output_shape_count = len(output.data.shape_keys.key_blocks) - 1 if output.data.shape_keys else 0
            output_side = output.get("aml_detected_source_side", "Unknown")
            symmetric_pair = bool(output.get("aml_symmetric_pair", False))
            symmetry_corrected = bool(output.get("aml_symmetry_corrected", False))
            expected_vertices = len(face_obj.data.vertices) + len(line_obj.data.vertices) * 2
            vertex_ok = len(output.data.vertices) == expected_vertices
            shape_ok = output_shape_count == source_shape_count + 2
            length_left = (
                output.data.shape_keys.key_blocks.get(LENGTH_KEY_NAMES["LEFT"])
                if output.data.shape_keys
                else None
            )
            length_right = (
                output.data.shape_keys.key_blocks.get(LENGTH_KEY_NAMES["RIGHT"])
                if output.data.shape_keys
                else None
            )
            has_drivers = bool(
                output.data.shape_keys
                and output.data.shape_keys.animation_data
                and output.data.shape_keys.animation_data.drivers
            )
            has_armature = any(modifier.type == "ARMATURE" for modifier in output.modifiers)
        except RuntimeError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        settings.last_message = (
            f"Auto source: {output_side} | Pair: {'Yes' if symmetric_pair else 'No'} | "
            f"Symmetry correction: {'Yes' if symmetry_corrected else 'No'} | "
            f"Mouth {found}/{len(MOUTH_KEYS)} | "
            f"ARKit {source_shape_count} + Length L/R: "
            f"{'Yes' if length_left and length_right else 'No'} | "
            f"Vertices: {'OK' if vertex_ok else 'ERROR'} | Drivers: {'ERROR' if has_drivers else 'None'} | "
            f"Armature: {'Yes' if has_armature else 'No'}"
        )
        self.report({"INFO"}, settings.last_message)
        return {"FINISHED"}


class AML_PT_main(Panel):
    bl_label = "ARKit Mouth Line"
    bl_idname = "AML_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "ARKit Mouth Line"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.aml_settings

        objects_box = layout.box()
        objects_box.label(text="Existing Objects")
        objects_box.prop(settings, "face_obj")
        objects_box.prop(settings, "line_obj")
        objects_box.prop(settings, "output_name")
        objects_box.label(text="Source side: Auto detect")
        objects_box.label(text="Output: Symmetric pair")
        objects_box.operator("aml.scan_keys", icon="VIEWZOOM")

        if settings.keys:
            keys_box = layout.box()
            keys_box.label(text="Detected Mouth Keys")
            keys_box.template_list(
                "AML_UL_keys",
                "",
                settings,
                "keys",
                settings,
                "active_key_index",
                rows=7,
            )

        length_box = layout.box()
        length_box.label(text=f"Left: {LENGTH_KEY_NAMES['LEFT']}")
        length_box.label(text=f"Right: {LENGTH_KEY_NAMES['RIGHT']}")
        length_box.label(text="Each: 0 = hidden, 1 = full length")

        column = layout.column(align=True)
        column.operator("aml.build_export_copy", icon="OUTLINER_OB_MESH")
        column.operator("aml.validate", icon="CHECKMARK")

        status_box = layout.box()
        status_box.label(text="Status")
        status_box.label(text=settings.last_message)


CLASSES = (
    AML_KeyItem,
    AML_Settings,
    AML_UL_keys,
    AML_OT_scan_keys,
    AML_OT_build_export_copy,
    AML_OT_validate,
    AML_PT_main,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.aml_settings = PointerProperty(type=AML_Settings)


def unregister():
    if hasattr(bpy.types.Scene, "aml_settings"):
        del bpy.types.Scene.aml_settings
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
