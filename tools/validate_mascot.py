"""Check exported mascot FBX files before they go into a mod.

Re-imports each build/<ABBR>/<ABBR>_mascot.fbx into an empty scene and checks
what a game import cares about: one mesh on one armature, a sane triangle
budget, every vertex skinned, real-world scale, feet on the ground, and a walk
animation whose last frame matches its first so it loops without a pop.

    python tools/validate_mascot.py            # every built team
    python tools/validate_mascot.py CHI DAL    # just these
"""

import sys
from pathlib import Path

import bpy  # must come first: bpy registers mathutils

REPO = Path(__file__).resolve().parent.parent
BUILD = REPO / "build"

MAX_TRIS = 20000
HEIGHT_RANGE = (1.8, 2.6)     # metres, top of head/ears/horns
GROUND_TOLERANCE = 0.03       # metres
LOOP_TOLERANCE = 1e-3         # metres of bone-head drift between first and last frame


def check(fbx_path):
    problems = []
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(fbx_path))
    objs = bpy.context.scene.objects
    arms = [o for o in objs if o.type == "ARMATURE"]
    meshes = [o for o in objs if o.type == "MESH"]
    if len(arms) != 1 or len(meshes) != 1:
        return [f"expected 1 armature + 1 mesh, got {len(arms)} + {len(meshes)}"], 0, 0.0
    arm, body = arms[0], meshes[0]

    tris = sum(len(p.vertices) - 2 for p in body.data.polygons)
    if tris > MAX_TRIS:
        problems.append(f"{tris} triangles exceeds budget of {MAX_TRIS}")

    bone_names = {b.name for b in arm.data.bones}
    group_names = {g.index: g.name for g in body.vertex_groups}
    unweighted = 0
    for v in body.data.vertices:
        if not any(g.weight > 0 and group_names.get(g.group) in bone_names for g in v.groups):
            unweighted += 1
    if unweighted:
        problems.append(f"{unweighted} vertices are not skinned to any bone")

    scene = bpy.context.scene
    scene.frame_set(int(scene.frame_start))
    world = [body.matrix_world @ v.co for v in body.data.vertices]
    top = max(c.z for c in world)
    bottom = min(c.z for c in world)
    if not HEIGHT_RANGE[0] <= top <= HEIGHT_RANGE[1]:
        problems.append(f"height {top:.2f} m outside {HEIGHT_RANGE}")
    if abs(bottom) > GROUND_TOLERANCE:
        problems.append(f"lowest point at {bottom:+.3f} m, expected on the ground (0)")

    action = arm.animation_data.action if arm.animation_data else None
    if action is None:
        problems.append("no animation on the armature")
    else:
        start, end = (int(f) for f in action.frame_range)
        if end - start < 2:
            problems.append(f"animation is only {end - start} frames long")

        def pose():
            return {pb.name: (arm.matrix_world @ pb.matrix).to_translation() for pb in arm.pose.bones}

        scene.frame_set(start)
        first = pose()
        scene.frame_set(end)
        last = pose()
        drift = max((first[n] - last[n]).length for n in first)
        if drift > LOOP_TOLERANCE:
            problems.append(f"walk does not loop: bones drift {drift * 1000:.1f} mm between frame {start} and {end}")
    return problems, tris, top


def main(argv):
    targets = [BUILD / a.upper() / f"{a.upper()}_mascot.fbx" for a in argv] or sorted(BUILD.glob("*/*_mascot.fbx"))
    if not targets:
        sys.exit("nothing to validate: run tools/build_mascot.py first")
    failed = 0
    for path in targets:
        if not path.exists():
            print(f"FAIL {path.relative_to(REPO)}: file not found")
            failed += 1
            continue
        problems, tris, top = check(path)
        summary = f"{tris} tris, {top:.2f} m tall"
        status = "FAIL" if problems else "ok  "
        print(f"{status} {path.stem:<14} {summary}")
        for p in problems:
            print(f"       - {p}")
        failed += bool(problems)
    print(f"\n{len(targets) - failed}/{len(targets)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
