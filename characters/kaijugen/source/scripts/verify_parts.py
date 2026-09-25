"""Verify the saved Kaijugen study, symmetry and editable control meshes."""
import json

import bpy
import bmesh
from mathutils.kdtree import KDTree

Expected = {'HEAD': 0, 'BODY': 0, 'TAIL': 1, 'ARM': None,
            'LEG': None, 'FOOT': 0}


def main():
  """Check all anatomical variants, live mirrors and control-surface topology."""
  report = []
  for title, axis in Expected.items():
    group = bpy.data.collections[title + ' · editable parts']
    objects = [obj for obj in group.objects if obj.type == 'MESH'
               and (obj.get('view') == 'large' or title in ('ARM','LEG','BODY'))]
    for obj in objects:
      if title not in ('ARM','LEG','BODY'):
        partner = group.objects.get(obj.name.removesuffix('large') + 'small')
        assert partner and partner.data == obj.data, obj.name
      if axis is not None:
        modifier = next(mod for mod in obj.modifiers if mod.type == 'MIRROR')
        assert tuple(modifier.use_axis) == tuple(i == axis for i in range(3))
        assert modifier.use_clip and modifier.use_mirror_merge, obj.name
        assert min(v.co[axis] for v in obj.data.vertices) >= -.00001, obj.name
      if 'topology' not in obj:
        continue
      smooth = next(mod for mod in obj.modifiers if mod.type == 'SUBSURF')
      smooth.show_viewport = False
      bpy.context.view_layer.update()
      evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
      data = evaluated.to_mesh()
      bm = bmesh.new()
      bm.from_mesh(data)
      boundary = sum(edge.is_boundary for edge in bm.edges)
      assert boundary == obj.get('eyeBoundaryEdges', 0), (title, boundary)
      assert all(edge.is_manifold or edge.is_boundary for edge in bm.edges)
      if not boundary:
        assert bm.calc_volume(signed=True) > 0, (title, 'inverted normals')
      assert all(face.calc_area() > 1e-8 for face in bm.faces), title
      assert all(len(face.verts) in (3, 4) for face in bm.faces), title
      error = 0
      if axis is not None:
        tree = KDTree(len(data.vertices))
        for i, vertex in enumerate(data.vertices):
          tree.insert(vertex.co, i)
        tree.balance()
        for vertex in data.vertices:
          point = vertex.co.copy()
          point[axis] *= -1
          error = max(error, tree.find(point)[2])
        assert error < 1e-6, (title, error)
      report.append(dict(part=title, variant=obj['view'], controlFaces=len(bm.faces),
                         quads=sum(len(face.verts) == 4 for face in bm.faces),
                         mirrorError=error, openEyeEdges=boundary))
      bm.free()
      evaluated.to_mesh_clear()
      smooth.show_viewport = True
  assert len(report) == 9
  assert len(bpy.data.scenes) == 7
  assert bpy.context.scene.compositing_node_group
  assert all(image.source != 'FILE' for image in bpy.data.images)
  print(json.dumps(report, indent=2))
  print('Verified nine quad cages, four symmetric forms, anatomical variants and studio scenes.')


if __name__ == '__main__':
  main()
