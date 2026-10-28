"""Render preview images of built mascots (no game or GPU needed).

For each team, renders the mascot from the front three-quarter view at four
points in the walk cycle and tiles them into build/<ABBR>/<ABBR>_preview.png.

    python tools/render_preview.py CHI
    python tools/render_preview.py ALL     # also writes docs/gallery.png
"""

import math
import sys
from pathlib import Path

import bpy  # must come first: bpy registers mathutils
from mathutils import Vector

REPO = Path(__file__).resolve().parent.parent
BUILD = REPO / "build"
FRAMES = (1, 9, 17, 25)   # quarter steps through the 32-frame walk
SIZE = 360


def setup(scene, arm):
    # Preview the walk in place: drop the lap-around-the-field constraint.
    for con in list(arm.constraints):
        arm.constraints.remove(con)
    cam_data = bpy.data.cameras.new("cam")
    cam_data.lens = 50
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (2.6, -4.6, 1.7)
    cam.rotation_euler = (Vector((0, 0, 1.15)) - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    sun.data.energy = 3.5
    sun.rotation_euler = (math.radians(50), 0, math.radians(30))
    scene.collection.objects.link(sun)
    bpy.ops.mesh.primitive_plane_add(size=6)
    world = bpy.data.worlds.new("w")
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.55, 0.62, 0.7, 1)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.8
    scene.world = world
    # Cycles on the CPU renders headless; Eevee and Workbench need a GPU context.
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 24
    scene.cycles.use_denoising = False
    scene.render.resolution_x = scene.render.resolution_y = SIZE


def render_team(abbr):
    blend = BUILD / abbr / f"{abbr}_mascot.blend"
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    scene = bpy.context.scene
    arm = next(o for o in scene.objects if o.type == "ARMATURE")
    setup(scene, arm)
    tiles = []
    for i, frame in enumerate(FRAMES):
        scene.frame_set(frame)
        path = BUILD / abbr / f"_tile{i}.png"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        tiles.append(path)
    sheet = bpy.data.images.new("sheet", SIZE * len(tiles), SIZE)
    pixels = [0.0] * (SIZE * len(tiles) * SIZE * 4)
    for t, path in enumerate(tiles):
        img = bpy.data.images.load(str(path))
        src = list(img.pixels)
        for y in range(SIZE):
            row = (y * SIZE * len(tiles) + t * SIZE) * 4
            pixels[row:row + SIZE * 4] = src[y * SIZE * 4:(y + 1) * SIZE * 4]
        path.unlink()
    sheet.pixels = pixels
    out = BUILD / abbr / f"{abbr}_preview.png"
    sheet.filepath_raw = str(out)
    sheet.file_format = "PNG"
    sheet.save()
    print(f"[{abbr}] preview -> {out.relative_to(REPO)}")


def main(argv):
    if not argv:
        sys.exit(__doc__)
    abbrs = sorted(p.name for p in BUILD.iterdir() if p.is_dir()) if argv[0].upper() == "ALL" else [a.upper() for a in argv]
    for abbr in abbrs:
        render_team(abbr)
    if argv[0].upper() == "ALL":
        make_gallery(abbrs)


def make_gallery(abbrs, cols=8):
    """One frame of every mascot in a grid: docs/gallery.png."""
    from PIL import Image

    cell = SIZE // 2
    rows = math.ceil(len(abbrs) / cols)
    sheet = Image.new("RGB", (cols * cell, rows * cell), "white")
    for i, abbr in enumerate(abbrs):
        tile = Image.open(BUILD / abbr / f"{abbr}_preview.png").crop((0, 0, SIZE, SIZE)).resize((cell, cell))
        sheet.paste(tile, ((i % cols) * cell, (i // cols) * cell))
    out = REPO / "docs" / "gallery.png"
    sheet.save(out)
    print(f"gallery -> {out.relative_to(REPO)}")


if __name__ == "__main__":
    main(sys.argv[1:])
