# Importing the mascots into Madden

This step happens on your Windows PC. It needs your own copy of Madden and a
Frostbite mod editor. **It hasn't been tested yet**: the editor, the game's asset
names and its mascot skeleton can't be checked from the build environment, so
treat the steps below as the plan to follow and correct as you go.

## 1. Check tool support for your Madden version

Madden modding uses community forks of the Frosty Toolsuite (an editor plus a
mod manager). Support arrives some time after each release, and for some
Madden versions mesh import didn't work at all. Before anything else, check
the Madden modding community (their Discord and the editor's release notes)
that your version has:

- a game profile for the editor, and
- **skinned mesh import** (not just texture or roster editing).

If mesh import isn't supported yet, the models in this repo are ready and waiting
for it.

## 2. Find the mascot assets

In the editor's Data Explorer, search for `mascot`. For each team you want to
replace, find the mascot's skinned mesh asset and **export the original to FBX**.
That export is your reference for:

- the game's **skeleton**: bone names and hierarchy,
- **scale and orientation**: compare its height with ours (2.16–2.30 m, Z-up, facing -Y in Blender),
- **material slots**: how many and in what order.

Some teams have no scanned mascot (18 shipped at Madden 26 launch, and more
came later). For those teams there may be no asset to replace.

## 3. Bind to the game's skeleton

The game moves mascots around the sideline with **its own animations**, which
drive **its own skeleton**. Our 17-bone rig and `Walk` action are for building
and previewing. In game, our mesh has to be skinned to the game's skeleton, and
then the game's existing behaviour makes it walk, cheer and react.

In Blender:

1. Import the game's exported mascot FBX and our `<TEAM>_mascot.blend` mesh into one scene.
2. Scale/align our mesh to the game mascot's rest pose.
3. Rename our vertex groups to the matching game bones (`hips`, `spine`,
   `chest`, `neck`, `head`, `upperarm.L`, `forearm.L`, `thigh.L`, `shin.L`, `foot.L`, ...),
   or use *Data Transfer → Vertex Groups* from the game mesh.
4. Parent our mesh to the game armature (Armature modifier), delete the game's
   mesh, and export mesh + armature to FBX with the same settings as the original.

Once the real bone names are known, this step can be scripted as a bone-name map in
`teams.json` plus a binding tool.

## 4. Import, package, play

1. In the editor, right-click the mascot mesh asset → **Import** → choose your FBX.
2. Assign/import textures if the game's material expects texture maps.
   Ours use flat colours, so you may need to bake them to a texture.
3. Repeat for each team, then **save the project as a mod** (`.fbmod`).
4. Enable it in the mod manager, launch Madden through the mod manager, and use
   offline modes only.
