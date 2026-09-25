# Kaijugen anatomical study

Open `parts_study.blend` in Blender 5.2 or later. The main scene contains
separate Head, Body, Tail, Arm, Leg and Foot meshes in a three-by-two grid.
Head, Tail and Foot share mesh data between their large and small views.
Body, Arm and Leg include independently authored small variants. The small
body has a gentler neck lean, and the small limbs follow the different cut
directions in the diagram. There are nine distinct anatomical control cages.

Head, Body and Foot use a welded X Mirror modifier. Tail uses a Y Mirror
modifier across its lengthwise center plane. Head details also mirror on X.
The primary shapes use editable quad cages and non-destructive subdivision.
Triangles are confined to terminal caps and the rear skull closure. The head
skin has two intentional eye openings, filled by separate eye surfaces.

F12 renders the grid through six linked studio scenes. The white lines
trace the original control-face boundaries on the smoothed surfaces using
face UV coordinates. They do not show subdivision tessellation. The
WIREFRAME collection contains these overlays; its objects are hidden in
solid view but enabled for rendering. Toggle their render visibility for
a shaded sheet. The normal viewport shows the native control edges.

Rebuild both PNG renders and the Blender source with:

```sh
/Applications/Blender.app/Contents/MacOS/Blender --background \
  --python characters/kaijugen/source/scripts/build_parts.py
```

Run this from the `polyworld_art` repository. Add `-- --preview` for a
smaller wireframe-only preview. `topology.json` records the control cages
with their symmetry modifiers evaluated and subdivision disabled.

The revised cages use measured contour and loop guides from the supplied
1536 by 1024 diagram. The main head is pinned to the measured facial projection; the other views
are framed to their measured heights. The color materials include a cool
shadow tint driven by surface normals. Toe caps and tapered hip markings use
procedural material masks. Neutral studio backgrounds retain soft cast
shadows through shadow-catcher floors.

To create the requested exact 50% comparison locally:

```sh
python3 characters/kaijugen/source/scripts/compare_parts.py \
  /absolute/path/to/reference.png \
  characters/kaijugen/renders/parts_wireframe.png \
  tmp/kaijugen/comparison
```

This writes `overlay_50.png`, `reference_and_render.png` and silhouette
comparison data. Reference-derived comparison images stay in ignored
`tmp/`, outside the redistributed asset set. The comparison does not warp
or independently align individual parts. Silhouette scores measure outline
and placement only; they do not measure topology or anatomical fidelity.
The head uses continuous forehead and jaw rows that redirect around the
eye apertures. Limb cut surfaces include inset cap loops. The foot redirects twenty toe
columns into twelve broader ankle columns using quads. The forms retain
inferred three-dimensional depth and bilateral symmetry; the head expression
and individual loop positions remain an interpretation of the diagram.
