"""Build a rigged, animated 3D mascot for one team (or all 32) and export it.

Each mascot is a single skinned mesh on a 17-bone humanoid skeleton with a
looping in-place walk cycle. Output per team, in build/<ABBR>/:

    <ABBR>_mascot.fbx    mesh + armature + "Walk" action, for import into a mod tool
    <ABBR>_mascot.blend  same scene plus a preview of the mascot walking around a
                         sideline-sized loop (open in Blender and press play)

Usage (run with the Python that has the `bpy` module installed):

    python tools/build_mascot.py --team CHI
    python tools/build_mascot.py --team ALL
"""

import argparse
import json
import math
import sys
from pathlib import Path

import bpy  # must come first: bpy registers bmesh and mathutils
import bmesh
from mathutils import Matrix, Vector

REPO = Path(__file__).resolve().parent.parent
CONFIG = REPO / "config" / "teams.json"
BUILD = REPO / "build"

FPS = 30
WALK_FRAMES = 32          # one full stride (two steps); frame 1 == frame 33
PREVIEW_FRAMES = 600      # 20 s lap around the preview loop
PREVIEW_RADIUS = 3.0      # metres

HEAD_STYLES = ("bear", "cat", "lion", "canine", "equine", "bird", "horned", "aquatic", "hog", "human")

# name: (head, tail) in metres. Blender is Z-up; the mascot faces -Y.
BONES = {
    "root":       ((0, 0, 0),          (0, 0.2, 0)),
    "hips":       ((0, 0, 1.00),       (0, 0, 1.15)),
    "spine":      ((0, 0, 1.15),       (0, 0, 1.35)),
    "chest":      ((0, 0, 1.35),       (0, 0, 1.55)),
    "neck":       ((0, 0, 1.55),       (0, 0, 1.62)),
    "head":       ((0, 0, 1.62),       (0, 0, 2.00)),
}
for side, sx in (("L", 1), ("R", -1)):
    BONES.update({
        f"upperarm.{side}": ((0.30 * sx, 0, 1.50), (0.36 * sx, 0, 1.22)),
        f"forearm.{side}":  ((0.36 * sx, 0, 1.22), (0.40 * sx, 0, 0.96)),
        f"thigh.{side}":    ((0.14 * sx, 0, 1.00), (0.14 * sx, 0, 0.55)),
        f"shin.{side}":     ((0.14 * sx, 0, 0.55), (0.14 * sx, 0, 0.12)),
        f"foot.{side}":     ((0.14 * sx, 0, 0.12), (0.14 * sx, -0.18, 0.03)),
    })
PARENTS = {
    "hips": "root", "spine": "hips", "chest": "spine", "neck": "chest", "head": "neck",
    "upperarm.L": "chest", "forearm.L": "upperarm.L",
    "upperarm.R": "chest", "forearm.R": "upperarm.R",
    "thigh.L": "hips", "shin.L": "thigh.L", "foot.L": "shin.L",
    "thigh.R": "hips", "shin.R": "thigh.R", "foot.R": "shin.R",
}
BONE_NAMES = list(BONES)

MATERIALS = ("jersey", "trim", "fur", "muzzle", "eye_white", "eye_black", "shoe", "glove", "accent")


def hex_rgba(value):
    value = value.lstrip("#")
    srgb = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    # Principled BSDF expects linear colour.
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb]
    return (*lin, 1.0)


def lighten(hex_value, amount=0.45):
    value = hex_value.lstrip("#")
    rgb = [int(value[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{round(c + (255 - c) * amount):02X}" for c in rgb)


def palette(team):
    return {
        "jersey": team["primary"],
        "trim": team["secondary"],
        "fur": team["fur"],
        "muzzle": lighten(team["fur"]),
        "eye_white": "#FAFAFA",
        "eye_black": "#111111",
        "shoe": "#1A1A1A",
        "glove": "#F2F2F2",
        "accent": team["accent"],
    }


class MeshBuilder:
    """Accumulates primitives into one bmesh, rigidly weighting each to a bone."""

    def __init__(self):
        self.bm = bmesh.new()
        self.deform = self.bm.verts.layers.deform.verify()

    def _tag(self, verts, material, bone):
        group = BONE_NAMES.index(bone)
        mat_index = MATERIALS.index(material)
        faces = {f for v in verts for f in v.link_faces}
        for v in verts:
            v[self.deform][group] = 1.0
        for f in faces:
            f.material_index = mat_index

    def sphere(self, center, scale, material, bone, segments=20, rings=12):
        m = Matrix.Translation(center) @ Matrix.Diagonal((*scale, 1.0))
        r = bmesh.ops.create_uvsphere(self.bm, u_segments=segments, v_segments=rings, radius=1.0, matrix=m)
        self._tag(r["verts"], material, bone)

    def cone(self, start, end, r1, r2, material, bone, segments=14, squash=None):
        """Cylinder/cone from start to end. squash optionally flattens it (x, y factors)."""
        start, end = Vector(start), Vector(end)
        axis = end - start
        up = "X" if abs(axis.normalized().y) > 0.9 else "Y"   # avoid a degenerate up axis
        rot = axis.to_track_quat("Z", up).to_matrix().to_4x4()
        m = Matrix.Translation((start + end) / 2) @ rot
        if squash:
            m = m @ Matrix.Diagonal((squash[0], squash[1], 1.0, 1.0))
        r = bmesh.ops.create_cone(self.bm, cap_ends=True, cap_tris=False, segments=segments,
                                  radius1=r1, radius2=r2, depth=axis.length, matrix=m)
        self._tag(r["verts"], material, bone)

    def to_mesh(self, name):
        mesh = bpy.data.meshes.new(name)
        self.bm.to_mesh(mesh)
        self.bm.free()
        for poly in mesh.polygons:
            poly.use_smooth = True
        return mesh


def build_body(mb):
    mb.sphere((0, 0, 1.30), (0.34, 0.26, 0.38), "jersey", "spine")
    mb.cone((0, 0, 1.38), (0, 0, 1.46), 0.35, 0.34, "trim", "chest", squash=(1.0, 0.8))
    mb.sphere((0, 0, 1.02), (0.30, 0.24, 0.18), "trim", "hips")
    mb.cone((0, 0, 1.55), (0, 0, 1.68), 0.10, 0.10, "fur", "neck")
    for side, sx in (("L", 1), ("R", -1)):
        mb.sphere((0.30 * sx, 0, 1.50), (0.12, 0.12, 0.12), "jersey", f"upperarm.{side}")
        mb.cone((0.30 * sx, 0, 1.50), (0.36 * sx, 0, 1.22), 0.09, 0.08, "jersey", f"upperarm.{side}")
        mb.cone((0.36 * sx, 0, 1.22), (0.40 * sx, 0, 0.98), 0.075, 0.065, "fur", f"forearm.{side}")
        mb.sphere((0.40 * sx, -0.01, 0.93), (0.09, 0.08, 0.10), "glove", f"forearm.{side}")
        mb.cone((0.14 * sx, 0, 1.00), (0.14 * sx, 0, 0.55), 0.12, 0.10, "trim", f"thigh.{side}")
        mb.cone((0.14 * sx, 0, 0.55), (0.14 * sx, 0, 0.12), 0.09, 0.08, "fur", f"shin.{side}")
        mb.sphere((0.14 * sx, -0.07, 0.07), (0.11, 0.19, 0.07), "shoe", f"foot.{side}")


def build_head(mb, style):
    hz = 1.84   # head centre height
    mb.sphere((0, 0, hz), (0.30, 0.28, 0.30), "fur", "head", segments=24, rings=16)
    for sx in (1, -1):
        mb.sphere((0.11 * sx, -0.24, hz + 0.06), (0.065, 0.04, 0.075), "eye_white", "head")
        mb.sphere((0.11 * sx, -0.275, hz + 0.05), (0.032, 0.02, 0.04), "eye_black", "head")

    def ears(pointed, height=0.20, radius=0.09, spread=0.17, material="fur"):
        for sx in (1, -1):
            base = (spread * sx, 0.02, hz + 0.20)
            if pointed:
                tip = (spread * sx * 1.35, 0.03, hz + 0.20 + height)
                mb.cone(base, tip, radius, 0.0, material, "head", segments=8, squash=(1.0, 0.45))
            else:
                mb.sphere((spread * 1.15 * sx, 0.02, hz + 0.22), (radius, 0.05, radius), material, "head")

    def snout(length=0.10, width=0.13, height=0.10, z=-0.07, material="muzzle", nose=True):
        mb.sphere((0, -0.24 - length * 0.4, hz + z), (width, length, height), material, "head")
        if nose:
            mb.sphere((0, -0.24 - length * 1.3, hz + z + height * 0.45), (0.045, 0.03, 0.035), "eye_black", "head")

    if style == "bear":
        ears(pointed=False, radius=0.10, spread=0.18)
        snout(length=0.12)
    elif style in ("cat", "lion"):
        if style == "lion":
            mb.sphere((0, 0.10, hz + 0.02), (0.42, 0.22, 0.40), "accent", "head")
        ears(pointed=True, height=0.17)
        snout(length=0.08, width=0.12, height=0.08)
    elif style == "canine":
        ears(pointed=True, height=0.22, radius=0.08)
        snout(length=0.20, width=0.11, height=0.09)
    elif style == "equine":
        ears(pointed=True, height=0.18, radius=0.06, spread=0.12)
        snout(length=0.26, width=0.14, height=0.13, z=-0.10, nose=False)
        for i in range(6):   # mane down the back of the head
            t = i / 5
            mb.sphere((0, 0.14 + 0.16 * t, hz + 0.26 - 0.42 * t), (0.05, 0.08, 0.08), "accent", "head", segments=10, rings=6)
    elif style == "bird":
        mb.cone((0, -0.22, hz - 0.03), (0, -0.50, hz - 0.08), 0.10, 0.0, "accent", "head", segments=12, squash=(1.2, 0.8))
        for i, sx in enumerate((-0.06, 0.0, 0.06)):   # crest feathers
            mb.cone((sx, 0.05, hz + 0.24), (sx * 1.5, 0.18, hz + 0.40 + 0.04 * (i == 1)), 0.05, 0.0, "fur", "head", segments=8)
    elif style == "horned":
        snout(length=0.12, width=0.17, height=0.11, z=-0.09)
        for sx in (1, -1):   # horn in three tapering segments, curling out then up
            p0 = Vector((0.24 * sx, 0.0, hz + 0.14))
            p1 = Vector((0.40 * sx, -0.02, hz + 0.18))
            p2 = Vector((0.50 * sx, -0.05, hz + 0.30))
            p3 = Vector((0.50 * sx, -0.10, hz + 0.44))
            mb.cone(p0, p1, 0.065, 0.05, "accent", "head", segments=10)
            mb.cone(p1, p2, 0.05, 0.035, "accent", "head", segments=10)
            mb.cone(p2, p3, 0.035, 0.0, "accent", "head", segments=10)
    elif style == "aquatic":
        snout(length=0.22, width=0.09, height=0.07, z=-0.06, material="fur", nose=False)
        mb.cone((0, 0.05, hz + 0.26), (0, 0.16, hz + 0.46), 0.12, 0.0, "fur", "head", segments=10, squash=(0.25, 1.0))
        mb.cone((0, 0.10, 1.48), (0, 0.32, 1.62), 0.10, 0.0, "fur", "chest", segments=10, squash=(0.25, 1.0))
    elif style == "hog":
        ears(pointed=True, height=0.12, radius=0.08, spread=0.19)
        mb.cone((0, -0.24, hz - 0.06), (0, -0.36, hz - 0.06), 0.10, 0.10, "muzzle", "head", segments=16)
        for sx in (1, -1):
            mb.sphere((0.035 * sx, -0.365, hz - 0.06), (0.022, 0.01, 0.03), "eye_black", "head")
    elif style == "human":
        mb.sphere((0, 0.06, hz + 0.14), (0.31, 0.28, 0.22), "jersey", "head")       # cap crown
        mb.cone((0, -0.24, hz + 0.13), (0, -0.24, hz + 0.15), 0.17, 0.17, "trim", "head",
                segments=16, squash=(1.0, 0.75))                                   # brim
        mb.sphere((0, -0.29, hz - 0.03), (0.05, 0.05, 0.06), "muzzle", "head")      # nose
        mb.cone((-0.10, -0.25, hz - 0.14), (0.10, -0.25, hz - 0.14), 0.015, 0.015, "eye_black", "head", segments=6)
    else:
        raise ValueError(f"unknown head_style {style!r}; expected one of {HEAD_STYLES}")


def build_armature(name):
    arm_data = bpy.data.armatures.new(name + "_rig")
    arm = bpy.data.objects.new(name + "_rig", arm_data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    for bone_name, (head, tail) in BONES.items():
        eb = arm_data.edit_bones.new(bone_name)
        eb.head, eb.tail = head, tail
        eb.roll = 0.0
    for child, parent in PARENTS.items():
        eb = arm_data.edit_bones[child]
        eb.parent = arm_data.edit_bones[parent]
        eb.use_connect = eb.head == eb.parent.tail
    bpy.ops.object.mode_set(mode="OBJECT")
    for pb in arm.pose.bones:
        pb.rotation_mode = "XYZ"
    return arm


def fcurves_of(action):
    """All F-curves of an action (Blender 4.4+ layered actions)."""
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                yield from bag.fcurves


def animate_walk(arm):
    """In-place walk loop. Positive X rotation swings a down-pointing bone backward."""
    pb = arm.pose.bones
    swing = math.radians(28)
    arm_swing = math.radians(22)
    for f in range(0, WALK_FRAMES + 1, 2):
        frame = f + 1
        ph = 2 * math.pi * f / WALK_FRAMES
        s, c = math.sin(ph), math.cos(ph)
        pb["thigh.L"].rotation_euler = (-swing * s, 0, 0)
        pb["thigh.R"].rotation_euler = (swing * s, 0, 0)
        # knee bends while that leg swings through (moving forward, i.e. cos > 0 for L)
        pb["shin.L"].rotation_euler = (math.radians(45) * max(0.0, c) + math.radians(5), 0, 0)
        pb["shin.R"].rotation_euler = (math.radians(45) * max(0.0, -c) + math.radians(5), 0, 0)
        pb["foot.L"].rotation_euler = (math.radians(-12) * s, 0, 0)
        pb["foot.R"].rotation_euler = (math.radians(12) * s, 0, 0)
        pb["upperarm.L"].rotation_euler = (arm_swing * s, 0, 0)
        pb["upperarm.R"].rotation_euler = (-arm_swing * s, 0, 0)
        pb["forearm.L"].rotation_euler = (math.radians(-20) - math.radians(12) * max(0.0, -s), 0, 0)
        pb["forearm.R"].rotation_euler = (math.radians(-20) - math.radians(12) * max(0.0, s), 0, 0)
        # body: bob twice per stride, sway hips, counter-twist chest, mascot head bounce
        pb["hips"].location = (0, 0.035 * math.cos(2 * ph), 0)       # bone-local Y is world up
        pb["hips"].rotation_euler = (0, math.radians(6) * s, math.radians(3) * s)
        pb["chest"].rotation_euler = (0, math.radians(-8) * s, 0)
        pb["head"].rotation_euler = (math.radians(4) * math.cos(2 * ph), math.radians(5) * s, 0)
        for name in ("thigh.L", "thigh.R", "shin.L", "shin.R", "foot.L", "foot.R",
                     "upperarm.L", "upperarm.R", "forearm.L", "forearm.R", "hips", "chest", "head"):
            pb[name].keyframe_insert("rotation_euler", frame=frame)
        pb["hips"].keyframe_insert("location", frame=frame)
    action = arm.animation_data.action
    action.name = "Walk"
    action.use_fake_user = True
    for fc in fcurves_of(action):
        for kp in fc.keyframe_points:
            kp.interpolation = "BEZIER"
        fc.modifiers.new("CYCLES")
    return action


def make_materials(team):
    colors = palette(team)
    mats = []
    for name in MATERIALS:
        mat = bpy.data.materials.new(f"{team['abbr']}_{name}")
        bsdf = mat.node_tree.nodes["Principled BSDF"]
        bsdf.inputs["Base Color"].default_value = hex_rgba(colors[name])
        bsdf.inputs["Roughness"].default_value = 0.35 if name in ("eye_white", "eye_black", "accent") else 0.8
        mat.diffuse_color = hex_rgba(colors[name])
        mats.append(mat)
    return mats


def add_preview_loop(arm):
    """Have the mascot walk laps of a circle in the .blend (not exported)."""
    bpy.ops.curve.primitive_bezier_circle_add(radius=PREVIEW_RADIUS, location=(0, 0, 0))
    path = bpy.context.active_object
    path.name = "preview_path"
    path.data.path_duration = PREVIEW_FRAMES
    con = arm.constraints.new("FOLLOW_PATH")
    con.target = path
    con.use_curve_follow = True
    con.forward_axis = "TRACK_NEGATIVE_Y"
    con.up_axis = "UP_Z"
    con.use_fixed_location = True
    con.offset_factor = 0.0
    con.keyframe_insert("offset_factor", frame=1)
    con.offset_factor = 1.0
    con.keyframe_insert("offset_factor", frame=PREVIEW_FRAMES + 1)
    bpy.context.scene.frame_end = PREVIEW_FRAMES
    return path


def build_team(team, out_root=BUILD):
    if team["head_style"] not in HEAD_STYLES:
        raise ValueError(f"{team['abbr']}: unknown head_style {team['head_style']!r}")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = FPS
    scene.frame_start, scene.frame_end = 1, WALK_FRAMES + 1
    name = f"{team['abbr']}_mascot"

    arm = build_armature(name)

    mb = MeshBuilder()
    build_body(mb)
    build_head(mb, team["head_style"])
    mesh = mb.to_mesh(name)
    for mat in make_materials(team):
        mesh.materials.append(mat)
    body = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(body)
    for bone_name in BONE_NAMES:
        body.vertex_groups.new(name=bone_name)
    body.parent = arm
    mod = body.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    body["mascot_name"] = team["mascot"]
    body["team"] = team["team"]

    animate_walk(arm)

    out_dir = out_root / team["abbr"]
    out_dir.mkdir(parents=True, exist_ok=True)
    fbx_path = out_dir / f"{name}.fbx"
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    body.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.export_scene.fbx(
        filepath=str(fbx_path),
        use_selection=True,
        object_types={"ARMATURE", "MESH"},
        add_leaf_bones=False,
        bake_anim=True,
        bake_anim_use_all_actions=False,
        bake_anim_use_nla_strips=False,
        bake_anim_force_startend_keying=True,
        mesh_smooth_type="FACE",
    )

    # Preview: move the walk onto an NLA track that repeats for the whole lap,
    # freeing the active action slot for the path-follow keys.
    walk = arm.animation_data.action
    arm.animation_data.action = None
    track = arm.animation_data.nla_tracks.new()
    track.name = "Walk"
    strip = track.strips.new("Walk", 1, walk)
    strip.repeat = PREVIEW_FRAMES / WALK_FRAMES
    add_preview_loop(arm)
    blend_path = out_dir / f"{name}.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

    tris = sum(len(p.vertices) - 2 for p in mesh.polygons)
    print(f"[{team['abbr']}] {team['mascot']:<11} {team['head_style']:<8} {tris:>6} tris -> {fbx_path.relative_to(REPO)}")
    return fbx_path


def load_teams():
    return json.loads(CONFIG.read_text())["teams"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--team", required=True, help="team abbreviation (e.g. CHI) or ALL")
    parser.add_argument("--out", type=Path, default=BUILD, help="output directory (default: build/)")
    args = parser.parse_args(argv)

    teams = load_teams()
    if args.team.upper() != "ALL":
        teams = [t for t in teams if t["abbr"] == args.team.upper()]
        if not teams:
            sys.exit(f"no team {args.team!r} in {CONFIG}")
    for team in teams:
        build_team(team, args.out.resolve())


if __name__ == "__main__":
    main()
