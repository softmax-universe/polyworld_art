"""Build the Kaijugen quad-mesh anatomical study and its Blender renders."""
import argparse
import json
import math
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Matrix, Vector

Root = Path(__file__).resolve().parents[2]
Tau = math.tau
HeadElevation = 12


def linear(value):
  """Convert an sRGB channel to scene-linear RGB."""
  return value / 12.92 if value < .04045 else ((value + .055) / 1.055) ** 2.4


def material(name, hexColor, roughness=.6, emission=False):
  """Create a matte studio material from a display color."""
  color = [linear(int(hexColor[i:i + 2], 16) / 255) for i in (0, 2, 4)]
  mat = bpy.data.materials.new(name)
  mat.diffuse_color = (*color, 1)
  mat.use_nodes = True
  shader = mat.node_tree.nodes.get('Principled BSDF')
  shader.inputs['Base Color'].default_value = (*color, 1)
  shader.inputs['Roughness'].default_value = roughness
  shader.inputs['Specular IOR Level'].default_value = .25
  if emission:
    shader.inputs['Emission Color'].default_value = (*color, 1)
    shader.inputs['Emission Strength'].default_value = .8
  return mat


def studio_tint(mat, lowColor):
  """Add a restrained normal-based cool shadow tint to the studio material."""
  tree = mat.node_tree
  shader = tree.nodes.get('Principled BSDF')
  color = tuple(shader.inputs['Base Color'].default_value)
  geometry = tree.nodes.new('ShaderNodeNewGeometry')
  dot = tree.nodes.new('ShaderNodeVectorMath')
  dot.operation = 'DOT_PRODUCT'
  dot.inputs[1].default_value = (-.75, -.45, .48)
  tree.links.new(geometry.outputs['Normal'], dot.inputs[0])
  ramp = tree.nodes.new('ShaderNodeValToRGB')
  ramp.color_ramp.elements[0].position = 0
  ramp.color_ramp.elements[0].color = (*lowColor, 1)
  ramp.color_ramp.elements[1].position = .7
  ramp.color_ramp.elements[1].color = (1, 1, 1, 1)
  tree.links.new(dot.outputs['Value'], ramp.inputs[0])
  mix = tree.nodes.new('ShaderNodeMixRGB')
  mix.blend_type = 'MULTIPLY'
  mix.inputs[0].default_value = 1
  mix.inputs[1].default_value = color
  tree.links.new(ramp.outputs['Color'], mix.inputs[2])
  tree.links.new(mix.outputs[0], shader.inputs['Base Color'])


def collection(name):
  """Create a named organizational collection."""
  item = bpy.data.collections.new(name)
  bpy.context.scene.collection.children.link(item)
  return item


def mesh(name, vertices, faces, materials, indices=None, smooth=True):
  """Create editable geometry and recalculate consistent outside normals."""
  data = bpy.data.meshes.new(name + ' · quads')
  data.from_pydata(vertices, [], faces)
  data.update()
  bm = bmesh.new()
  bm.from_mesh(data)
  bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=.00001)
  bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_edges], context='VERTS')
  bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
  if all(not edge.is_boundary for edge in bm.edges) and bm.calc_volume(signed=True) < 0:
    bmesh.ops.reverse_faces(bm, faces=list(bm.faces))
  bm.to_mesh(data)
  bm.free()
  for mat in materials:
    data.materials.append(mat)
  for i, poly in enumerate(data.polygons):
    poly.use_smooth = smooth
    poly.material_index = indices[i] if indices else 0
  uv = data.uv_layers.new(name='Control face coordinates')
  for poly in data.polygons:
    corners = [(0, 0), (1, 0), (1, 1), (0, 1)]
    if len(poly.vertices) == 3:
      corners = [(0, 0), (1, 0), (0, 1)]
    for loop, co in zip(poly.loop_indices, corners):
      uv.data[loop].uv = co
  obj = bpy.data.objects.new(name, data)
  return obj


def loft(name, rings, color=None, caps=True):
  """Join authored cross sections with quads and preserve deliberate socket rims."""
  vertices = [tuple(point) for ring in rings for point in ring]
  starts, total = [], 0
  for ring in rings:
    starts.append(total)
    total += len(ring)
  faces, indices = [], []
  for j in range(len(rings) - 1):
    count, nextCount = len(rings[j]), len(rings[j + 1])
    a, b = starts[j], starts[j + 1]
    if count == nextCount:
      for i in range(count):
        faces.append((a + i, a + (i + 1) % count,
                      b + (i + 1) % count, b + i))
        indices.append(color(j, i) if color else 0)
    else:
      assert (count, nextCount) == (20, 12), name
      # Redirect five toe edges into three broad instep edges with four quads.
      for quarter in range(4):
        lower = [a + (quarter * 5 + i) % 20 for i in range(6)]
        upper = [b + (quarter * 3 + i) % 12 for i in range(4)]
        patches = [(lower[0], upper[0], upper[1], lower[1]),
                   (lower[1], upper[1], lower[3], lower[2]),
                   (upper[1], upper[2], lower[4], lower[3]),
                   (upper[2], upper[3], lower[5], lower[4])]
        faces.extend(patches)
        indices.extend([0] * len(patches))
  capStart = len(faces)
  if caps:
    for ringIndex in (0, len(rings) - 1):
      count, start = len(rings[ringIndex]), starts[ringIndex]
      center = sum((Vector(v) for v in rings[ringIndex]), Vector()) / count
      innerStart = len(vertices)
      vertices.extend(tuple(center.lerp(Vector(v), .48)) for v in rings[ringIndex])
      centerIndex = len(vertices)
      vertices.append(tuple(center))
      for i in range(count):
        faces.append((start + i, start + (i + 1) % count,
                      innerStart + (i + 1) % count, innerStart + i))
        faces.append((centerIndex, innerStart + i, innerStart + (i + 1) % count))
        indices.extend((0, 0))
  obj = mesh(name, vertices, faces, [Green, Yellow], indices)
  if caps:
    for poly in list(obj.data.polygons)[capStart:]:
      poly.use_smooth = False
    rim = obj.data.attributes.new('Socket rim', 'BOOLEAN', 'EDGE')
    for edge in obj.data.edges:
      a, b = edge.vertices
      rim.data[edge.index].value = (a < len(rings[0]) and b < len(rings[0])) or (
        starts[-1] <= a < total and starts[-1] <= b < total)
  obj['topology'] = 'Authored quad strips; radial triangles only at cut caps.'
  return obj


def reference_point(point, depth=0, origin=(0, 0), angle=0, elevation=14):
  """Lift a measured reference pixel into an orthographic modeling view."""
  azimuth = math.radians(angle)
  elevation = math.radians(elevation)
  pixelScale = 1536 / 16.8
  horizontal = (point[0] - origin[0]) / pixelScale
  vertical = (origin[1] - point[1]) / pixelScale
  x = (horizontal + math.sin(azimuth) * depth) / math.cos(azimuth)
  z = (vertical - math.sin(elevation) *
       (math.sin(azimuth) * x + math.cos(azimuth) * depth)) / math.cos(elevation)
  return Vector((x, depth, z))


def reference_rings(name, sections, origin, angle=0, color=None, sectors=12, tilt=0):
  """Loft measured section endpoints with explicitly inferred depth."""
  rings = []
  for first, last, depth, thickness in sections:
    a = reference_point(first, depth, origin, angle)
    b = reference_point(last, depth, origin, angle)
    center = (a + b) / 2
    radial = (a - b) / 2
    ring = []
    for i in range(sectors):
      phase = Tau * i / sectors
      point = center + radial * math.cos(phase)
      point += Vector((0, thickness * math.sin(phase),
                       tilt * thickness * math.sin(phase)))
      if name.startswith('Arm'):
        point.x *= 1.18
      if name.startswith('Leg'):
        point.x *= 1.25
      ring.append(tuple(point))
    rings.append(ring)
  return loft(name, rings, color)


def traced_rings(name, sections, origin, color=None, sectors=12):
  """Lift measured section ellipses into editable three-dimensional quad rings."""
  rings=[]
  for first,last,depth,thickness,sag in sections:
    a,b=Vector(first),Vector(last)
    center,radial=(a+b)/2,(a-b)/2
    ring=[]
    for i in range(sectors):
      phase=Tau*i/sectors
      pixel=center+radial*math.cos(phase)+Vector(sag)*math.sin(phase)
      point=reference_point(pixel,depth-thickness*math.sin(phase),origin)
      ring.append(tuple(point))
    rings.append(ring)
  return loft(name,rings,color)


def arm_small():
  """Author the smaller arm's lateral shoulder cut and tighter elbow directly."""
  sections=[
    ((433,606),(474,700),.35,.42,(-14,7)),
    ((393,630),(463,716),.18,.52,(-9,12)),
    ((371,666),(463,727),.03,.58,(-8,12)),
    ((367,701),(465,744),.02,.54,(-5,12)),
    ((375,737),(465,755),-.02,.50,(-5,10)),
    ((354,755),(454,791),-.10,.53,(-10,12)),
    ((331,771),(419,819),-.21,.49,(-11,11)),
    ((309,783),(366,842),-.31,.39,(-8,9)),
    ((304,803),(347,850),-.34,.29,(-5,7)),
    ((321,833),(342,846),-.34,.12,(-2,3))]
  return [traced_rings('Arm · small lateral cut',sections,(400,850))]


def leg_small():
  """Author the smaller thigh's side cut, inner marking and forward ankle bend."""
  sections=[
    ((935,631),(984,711),.40,.43,(-14,7)),
    ((889,652),(972,744),.20,.67,(-10,11)),
    ((850,690),(947,770),.00,.78,(-8,12)),
    ((838,734),(946,781),-.05,.70,(-4,10)),
    ((886,824),(945,774),.02,.55,(-4,10)),
    ((874,852),(981,829),-.09,.50,(-5,8)),
    ((872,863),(982,851),-.23,.56,(-4,7)),
    ((872,878),(980,873),-.24,.60,(-4,6)),
    ((881,889),(975,883),-.24,.53,(-3,4))]
  def color(j,i):
    """Limit the gold inset to the inner lower thigh."""
    return int(j == 3 and i in (0,1,10,11))
  obj=traced_rings('Leg · small lateral cut',sections,(920,892),color)
  for vertex in obj.data.vertices:
    vertex.co.x *= 1.09
  return [obj]


def body(lean=.60):
  """Shape a broad low torso using the reference's row heights and hip creases."""
  profiles = [
    (.03, .72, .45, -.10), (.19, 1.02, .70, -.08),
    (.62, 1.37, .92, -.06), (1.16, 1.40, .98, -.04),
    (1.74, 1.18, .86, .00), (2.27, .87, .65, .04),
    (2.78, .68, .50, .07), (3.12, .47, .38, .09),
    (3.26, .44, .36, .09), (3.47, .44, .36, .09)]
  angles = [0, 18, 40, 41.5, 53, 90, 115, 148, 180,
            212, 245, 270, 307, 318.5, 320, 342]
  rings = []
  for j, (z, width, depth, shift) in enumerate(profiles):
    ring = []
    low = math.exp(-((z - .65) / .70) ** 2)
    for i, degree in enumerate(angles):
      angle = math.radians(degree)
      x = math.sin(angle) * width * 1.225
      y = shift - math.cos(angle) * depth * 1.24
      bend=lean*max(0,min(1,(z-1.0)/2.0))
      y-=bend
      height=z+bend*math.tan(math.radians(14))*math.cos(math.radians(25))
      if i in (3, 13):
        x *= 1 - .11 * low
        y += .33 * low
        height += .07 * low
      if i in (4, 12):
        x *= 1 + .11 * low
        y -= .25 * low
        height -= .03 * low
      if j < 2 and i in (2, 14):
        height += .13 * (1 - j * .5)
      if j >= 7:
        height -= .13 * (y - shift + bend)
      ring.append((x, y, height))
    rings.append(ring)
  def color(j, i):
    """Keep the bib broad and taper the separate inner-hip insets."""
    return int((j < 7 and i in (0, 1, 14, 15)) or
               (j < 3 and i in (3, 12)))
  obj=loft('Body · pear torso', rings, color)
  obj.data.materials.append(hip_material())
  for j in (2,):
    for i in (3,12):
      obj.data.polygons[j*len(angles)+i].material_index=2
  return [obj]


def body_small():
  """Keep the smaller torso's neck less projected while preserving its quad layout."""
  return body(lean=.30)


def hip_material():
  """Taper the upper hip markings to the inner corner of their surface patch."""
  mat=Green.copy()
  mat.name='Body · tapered hip inset tips'
  nodes,links=mat.node_tree.nodes,mat.node_tree.links
  coordinates=nodes.new('ShaderNodeTexCoord')
  axes=nodes.new('ShaderNodeSeparateXYZ')
  links.new(coordinates.outputs['UV'],axes.inputs[0])
  diagonal=nodes.new('ShaderNodeMath')
  diagonal.operation='ADD'
  links.new(axes.outputs['X'],diagonal.inputs[0])
  links.new(axes.outputs['Y'],diagonal.inputs[1])
  mask=nodes.new('ShaderNodeMath')
  mask.operation='LESS_THAN'
  links.new(diagonal.outputs[0],mask.inputs[0])
  mask.inputs[1].default_value=1
  shade=next(node for node in nodes if node.type=='MIX_RGB' and node.blend_type=='MULTIPLY')
  colors=nodes.new('ShaderNodeMixRGB')
  colors.inputs[1].default_value=Green.diffuse_color
  colors.inputs[2].default_value=Yellow.diffuse_color
  links.new(mask.outputs[0],colors.inputs[0])
  links.new(colors.outputs[0],shade.inputs[1])
  return mat


def tail():
  """Follow the measured thick crescent and the broad terminal cut."""
  sections = [
    ((1060, 226), (1060, 369), 0, .66),
    ((1090, 239), (1100, 390), 0, .68),
    ((1157, 248), (1156, 401), 0, .67),
    ((1215, 238), (1212, 395), 0, .63),
    ((1258, 210), (1266, 373), 0, .55),
    ((1287, 175), (1311, 335), 0, .48),
    ((1302, 136), (1345, 278), 0, .38),
    ((1301, 107), (1365, 218), 0, .30),
    ((1295, 81), (1353, 150), 0, .20),
    ((1298, 79), (1325, 104), 0, .085),
    ((1295, 78), (1298, 81), 0, .009)]
  def color(j, i):
    """Run the underside band through the outer curve's lower three strips."""
    return int(j < 8 and i in (4, 5, 6, 7))
  return [reference_rings('Tail · rising crescent', sections, (1200, 405),
                          13, color)]


def arm():
  """Follow the cut shoulder, recessed elbow and rounded forearm with traced loops."""
  sections=[
    ((192,554),(103,638),.05,.52,(12,12)),
    ((232,601),(125,671),.0,.61,(8,15)),
    ((259,659),(143,703),.0,.66,(5,17)),
    ((274,716),(148,722),.0,.71,(0,16)),
    ((267,768),(146,719),.0,.69,(-8,17)),
    ((247,806),(122,743),-.05,.63,(-10,15)),
    ((209,832),(85,769),-.15,.58,(-10,14)),
    ((160,847),(57,795),-.2,.49,(-9,10)),
    ((123,872),(44,835),-.27,.40,(-5,8)),
    ((95,882),(52,861),-.3,.22,(-2,4))]
  obj=traced_rings('Arm · bent elbow',sections,(160,885))
  for vertex in obj.data.vertices:
    vertex.co.x *= 1.055
  return [obj]


def leg():
  """Follow the slanted thigh loops into the compressed knee and broad base."""
  sections = [
    ((709, 530), (580, 605), .05, .55),
    ((742, 566), (587, 636), .05, .66),
    ((781, 625), (570, 670), -.02, .80),
    ((792, 687), (568, 716), -.10, .88),
    ((778, 741), (589, 786), -.08, .78),
    ((744, 784), (641, 818), .10, .57),
    ((773, 819), (623, 841), -.05, .58),
    ((790, 865), (606, 877), -.35, .85),
    ((781, 899), (608, 905), -.45, .86)]
  def color(j, i):
    """Place the yellow marking on the front-left inner thigh only."""
    return int((1 <= j <= 4 and i == 6) or (2 <= j <= 3 and i == 7))
  return [reference_rings('Leg · thigh knee and ankle', sections,
                          (690, 914), 0, color, tilt=.55)]


def foot():
  """Blend three toe lobes into one broad foot and a short ankle socket."""
  half = [(0,-1.04),(.18,-1.00),(.235,-.86),(.27,-.80),
          (.42,-.94),(.65,-.94),(.76,-.77),(.72,-.30),
          (.60,.24),(.35,.50),(0,.51)]
  outline = half + [(-x, y) for x, y in half[-2:0:-1]]
  count = len(outline)
  profiles = [(0, .92, 0), (.10, 1, 0), (.21, 1, .03),
              (.43, .98, .15), (.55, .90, .48),
              (.66, 1, 1), (.84, 1, 1)]
  rings = []
  for z, scale, blend in profiles:
    ring = []
    count = 12 if blend >= .48 else 20
    for i in range(count):
      sample = i * len(outline) / count
      first = int(sample)
      x, y = Vector(outline[first]).lerp(
        Vector(outline[(first + 1) % len(outline)]), sample - first)
      angle = Tau * i / count
      ankleX = .42 * math.sin(angle)
      ankleY = -.14 - .32 * math.cos(angle)
      height = z
      if z == .43:
        toeHeights = {0:.38,1:.34,2:.24,3:.23,4:.34,5:.37,6:.29}
        height = toeHeights.get(min(i, count - i), z)
      ring.append((x * scale * (1 - blend) + ankleX * blend,
                   (y * scale * (1 - blend) + ankleY * blend) * 1.4,
                   height + .079 * blend))
    rings.append(ring)
  def color(j, i):
    """Color the rounded toe ends while leaving the valleys green."""
    return int(j <= 2 and i in (0,4,5,count-1,count-5,count-6))
  obj=loft('Foot · three integral toes', rings, color)
  obj.data.materials.clear()
  obj.data.materials.append(foot_material())
  for polygon in obj.data.polygons:
    polygon.material_index=0
  return [obj]


def foot_material():
  """Wrap rounded yellow caps across the three integral toe surfaces."""
  mat=Green.copy()
  mat.name='Foot · rounded butter-yellow toe caps'
  nodes,links=mat.node_tree.nodes,mat.node_tree.links
  coordinates=nodes.new('ShaderNodeTexCoord')
  masks=[]
  for x,radius in [(0,.235),(.56,.205),(-.56,.205)]:
    delta=nodes.new('ShaderNodeVectorMath')
    delta.operation='SUBTRACT'
    links.new(coordinates.outputs['Object'],delta.inputs[0])
    delta.inputs[1].default_value=(x,-1.31,.115)
    normalized=nodes.new('ShaderNodeVectorMath')
    normalized.operation='DIVIDE'
    links.new(delta.outputs['Vector'],normalized.inputs[0])
    normalized.inputs[1].default_value=(radius,.38,.35)
    squared=nodes.new('ShaderNodeVectorMath')
    squared.operation='DOT_PRODUCT'
    links.new(normalized.outputs['Vector'],squared.inputs[0])
    links.new(normalized.outputs['Vector'],squared.inputs[1])
    mask=nodes.new('ShaderNodeMath')
    mask.operation='LESS_THAN'
    links.new(squared.outputs['Value'],mask.inputs[0])
    mask.inputs[1].default_value=1
    masks.append(mask.outputs[0])
  result=masks[0]
  for mask in masks[1:]:
    union=nodes.new('ShaderNodeMath')
    union.operation='MAXIMUM'
    links.new(result,union.inputs[0])
    links.new(mask,union.inputs[1])
    result=union.outputs[0]
  shade=next(node for node in nodes if node.type=='MIX_RGB' and node.blend_type=='MULTIPLY')
  colors=nodes.new('ShaderNodeMixRGB')
  colors.inputs[1].default_value=Green.diffuse_color
  colors.inputs[2].default_value=Yellow.diffuse_color
  links.new(result,colors.inputs[0])
  links.new(colors.outputs[0],shade.inputs[1])
  return mat


def curve(name, points, radius, mat):
  """Create a short three-dimensional detail curve."""
  data = bpy.data.curves.new(name, 'CURVE')
  data.dimensions = '3D'
  data.resolution_u = 12
  data.bevel_depth = radius
  data.bevel_resolution = 2
  spline = data.splines.new('BEZIER')
  spline.bezier_points.add(len(points) - 1)
  for point, position in zip(spline.bezier_points, points):
    point.co = position
    point.handle_left_type = 'AUTO'
    point.handle_right_type = 'AUTO'
  data.materials.append(mat)
  return bpy.data.objects.new(name, data)


def head():
  """Build brow, nose and jaw quad rows around two forward-facing eye holes."""
  origin, angle = (160,380), -50
  guides = [
    [(151,129),(180,132),(210,141),(237,150),(259,160),(276,181),(289,207),(295,236)],
    [(127,164),(163,170),(190,179),(210,181),(231,179),(253,198),(280,224),(297,260)],
    [(113,195),(154,204),(173,194),(194,187),(215,184),(233,200),(259,223),(298,282)],
    [(103,231),(143,238),(163,219),(181,208),(201,201),(222,207),(242,233),(297,299)],
    [(98,240),(141,249),(158,243),(178,230),(199,219),(224,218),(241,239),(296,310)],
    [(94,247),(134,260),(158,257),(179,247),(201,237),(225,231),(242,247),(293,318)],
    [(92,263),(133,275),(163,268),(183,261),(205,252),(229,249),(247,266),(290,326)],
    [(90,278),(139,297),(174,278),(192,280),(212,273),(228,261),(249,286),(286,336)],
    [(90,286),(141,307),(180,293),(203,292),(221,291),(241,307),(263,305),(279,345)],
    [(89,323),(145,339),(190,335),(221,322),(239,311),(256,321),(270,333),(279,343)],
    [(98,343),(144,351),(190,354),(217,347),(239,338),(252,342),(262,348),(267,353)],
    [(108,358),(145,366),(185,369),(211,364),(231,355),(242,357),(246,363),(243,368)]]
  depths = [
    [0,.25,.65,.90,1.20,1.40,1.50,1.55],
    [0,-.35,-.22,.10,.36,.66,1.02,1.42],
    [0,-.48,-.39,-.25,.02,.27,.87,1.40],
    [0,-.70,-.66,-.54,-.404,-.29,.30,1.32],
    [0,-.79,-.63,-.52,-.40,-.27,.24,1.27],
    [0,-.84,-.56,-.48,-.38,-.25,.23,1.20],
    [0,-.86,-.56,-.49,-.39,-.28,.25,1.15],
    [0,-.89,-.54,-.45,-.36,-.28,.31,1.10],
    [0,-.90,-.74,-.58,-.58,-.25,.43,1.03],
    [0,-.85,-.68,-.45,-.32,.0,.42,.87],
    [0,-.80,-.54,-.20,-.20,-.10,.05,.90],
    [0,-.73,-.54,-.38,-.20,.03,.40,.90]]
  guides[0]=[(154,124),(186,131),(225,140),(260,153),
             (278,181),(287,208),(295,237),(302,264)]
  depths[0]=[0,.20,.35,.50,.65,.85,1.0,1.15]
  guides[9]=[(89,323),(135,330),(174,341),(215,323),
             (244,307),(257,325),(270,333),(279,343)]
  guides[10]=[(98,343),(149,351),(182,361),(218,350),
              (255,325),(261,340),(262,348),(267,353)]
  guides[8][4]=(222,291)
  depths[8][4]=-.50
  guides[3][2:6]=[(163,223),(181,209),(201,198),(222,202)]
  guides[4][2:6]=[(158,255),(178,242),(199,226),(224,219)]
  guides[5][2:6]=[(158,263),(179,250),(201,233),(225,223)]
  depths[1][2]=-.36
  depths[2][3]=-.36
  depths[2][4]=-.20
  depths[2][5]=.10
  depths[3][2:6]=[-.478,-.400,-.336,-.271]
  depths[4][2:6]=[-.571,-.486,-.399,-.271]
  guides[5][0]=(94,247)
  guides[5][1]=(134,260)
  guides[8][0]=(90,283)
  guides[-1]=[(108,368),(145,376),(185,379),(211,368),
              (231,357),(242,352),(246,352),(243,351)]
  depths[5][1]=-.68
  depths[8][1]=-.79
  cheekPairs=[((8,2),47),((8,3),38),((8,4),28),((8,5),30),
              ((9,2),33),((9,3),18),((9,4),30),((10,2),45)]
  for (j,i),farX in cheekPairs:
    depths[j][i]=(guides[j][i][0]+farX-320)/(2*(1536/16.8)*math.sin(math.radians(50)))
  pairedEyes=[
    ((5,2),(167,257),(78,235)),((5,3),(184,249),(69,219)),
    ((5,4),(204,240),(62,208)),((5,5),(222,234),(59,201)),
    ((6,5),(229,251),(54,223)),((7,5),(218,267),(56,237)),
    ((7,4),(205,273),(59,242)),((7,3),(193,274),(63,243)),
    ((7,2),(174,267),(69,241)),((6,2),(167,262),(75,239))]
  for (j,i),near,far in pairedEyes:
    guides[j][i]=near
    depths[j][i]=(near[0]+far[0]-origin[0]*2)/(2*(1536/16.8)*math.sin(math.radians(50)))
  rows, columns = len(guides), len(guides[0])
  points = []
  for guide, values in zip(guides,depths):
    for i,(pixel,depth) in enumerate(zip(guide,values)):
      if i == 0:
        depth = (pixel[0]-origin[0])/(1536/16.8)/-math.sin(math.radians(angle))
      point = reference_point(pixel,depth,origin,angle,HeadElevation)
      if i == 0:
        point.x = 0
      points.append(point)
  vertices,faces,indices,boundaries = [],[],[],[]
  for side in (1,-1):
    start = len(vertices)
    vertices.extend((side*p.x,p.y,p.z) for p in points)
    for j in range(rows-1):
      for i in range(columns-1):
        if i in (0,1,5,6) or (j in (5,6) and i in (2,3,4)):
          continue
        face=(start+j*columns+i,start+j*columns+i+1,
              start+(j+1)*columns+i+1,start+(j+1)*columns+i)
        faces.append(face if side == 1 else face[::-1])
        index = 2 if j == 4 and i in (2,3,4) else 0
        if (j >= 8 and i <= 5) or (j == 7 and i == 0):
          index = 1
        indices.append(index)
    frontRows=[0,1,2,3,4,5,8,9,10,11]
    for first,last in zip(frontRows,frontRows[1:]):
      center=(start+first*columns,start+first*columns+1,
              start+last*columns+1,start+last*columns)
      faces.append(center if side == 1 else center[::-1])
      indices.append(int(first>=8))
      a=[start+j*columns+2 for j in range(first,last+1)]
      b0,b1=start+first*columns+1,start+last*columns+1
      patches=[(b0,a[0],a[1],b1)] if last-first == 1 else [
        (b0,a[0],a[1],a[2]),(b0,a[2],a[3],b1)]
      faces.extend(face if side == 1 else face[::-1] for face in patches)
      indices.extend([int(first>=8)]*len(patches))
    sideRows=[0,1,4,7,10,11]
    for first,last in zip(sideRows,sideRows[1:]):
      a=[start+j*columns+5 for j in range(first,last+1)]
      b0,b1=start+first*columns+6,start+last*columns+6
      patches=[(a[0],b0,b1,a[1])] if last-first == 1 else [
        (a[0],b0,a[2],a[1]),(b0,b1,a[3],a[2])]
      faces.extend(face if side == 1 else face[::-1] for face in patches)
      indices.extend([int(first>=10)]*len(patches))
      outer=(b0,start+first*columns+7,start+last*columns+7,b1)
      faces.append(outer if side == 1 else outer[::-1])
      indices.append(0)
    boundary = [start+i for i in range(columns)]
    boundary += [start+j*columns+columns-1 for j in sideRows[1:]]
    boundary += [start+(rows-1)*columns+i for i in range(columns-2,-1,-1)]
    boundaries.append(boundary)
  perimeter = boundaries[0] + list(reversed(boundaries[1][1:-1]))
  previous = perimeter
  for j,(scale,depth) in enumerate([(.93,.03),(.60,1.10),(.24,1.70)]):
    current=[]
    for index in perimeter:
      p=Vector(vertices[index])
      y=p.y+depth if j == 0 else p.y*.35+depth if j == 1 else depth
      centerZ=1.40 if j == 0 else 1.25 if j == 1 else 1.20
      z=centerZ+(p.z-centerZ)*(.96 if j == 0 else scale)
      current.append(len(vertices))
      vertices.append((p.x*scale,y,z))
    for i in range(len(previous)):
      faces.append((previous[i],previous[(i+1)%len(previous)],
                    current[(i+1)%len(current)],current[i]))
      indices.append(int(j == 0 and Vector(vertices[previous[i]]).z < .65))
    previous=current
  center=len(vertices)
  vertices.append((0,1.78,1.20))
  for i in range(len(previous)):
    faces.append((previous[i],previous[(i+1)%len(previous)],center))
    indices.append(0)
  headGreen=Green.copy()
  headGreen.name='Head · soft leaf-green planes'
  ramp=next(node for node in headGreen.node_tree.nodes if node.type=='VALTORGB')
  ramp.color_ramp.elements[0].color=(.48,.60,.43,1)
  skin=mesh('Head · ocular loops and skull',vertices,faces,[headGreen,Yellow,Brow],indices)
  skin['topology']='Continuous forehead, brow, nose and jaw quad rows around two shaped eye apertures.'
  ridge=[points[4*columns+i] for i in (2,3,4,5)]
  corners=[points[j*columns+i] for (j,i),near,far in pairedEyes]
  creases=skin.data.attributes.new('crease_edge','FLOAT','EDGE')
  tips=skin.data.attributes.new('crease_vert','FLOAT','POINT')
  for vertex in skin.data.vertices:
    p=Vector((abs(vertex.co.x),vertex.co.y,vertex.co.z))
    if any((p-q).length<.0001 for q in corners):
      tips.data[vertex.index].value=1.0
  for edge in skin.data.edges:
    ps=[skin.data.vertices[i].co for i in edge.vertices]
    if all(any((Vector((abs(p.x),p.y,p.z))-q).length<.0001 for q in ridge) for p in ps):
      creases.data[edge.index].value=.7
  for edge in skin.data.edges:
    adjoining=[poly.material_index for poly in skin.data.polygons
               if all(i in poly.vertices for i in edge.vertices)]
    if 0 in adjoining and 1 in adjoining:
      creases.data[edge.index].value=.55
  skin['eyeBoundaryEdges']=20
  skin['referenceViewAngle']=angle
  parts=[skin]
  apertureIndices=[(5,2),(5,3),(5,4),(5,5),(6,5),(7,5),(7,4),(7,3),(7,2),(6,2)]
  aperture=[points[j*columns+i] for j,i in apertureIndices]
  count=len(aperture)
  eyeCenter=reference_point((195,254),-.435,origin,angle,HeadElevation)
  eyeVerts=[tuple(p+Vector((0,.004,0))) for p in aperture]
  for p in aperture:
    q=p.lerp(eyeCenter,.55)
    q.y-=.035
    eyeVerts.append(tuple(q))
  eyeVerts.append(tuple(eyeCenter+Vector((0,-.06,0))))
  eyeFaces=[]
  for i in range(count):
    eyeFaces.append((i,(i+1)%count,count+(i+1)%count,count+i))
    eyeFaces.append((count+i,count+(i+1)%count,count*2))
  parts.append(mesh('Head · golden eye',eyeVerts,eyeFaces,[Gold]))
  parts.append(eye_patch('Head · pupil',aperture,eyeVerts,eyeFaces,angle,
                        (181,250),(12,22),Dark))
  parts.append(eye_patch('Head · glint',aperture,eyeVerts,eyeFaces,angle,
                        (211,248),(7,5),White))
  lid=[]
  for p in aperture[:4]:
    lid.append(tuple(p+Vector((0,-.014,0))))
    lid.append(tuple(p.lerp(eyeCenter,.13)+Vector((0,-.025,0))))
  parts.append(mesh('Head · upper eyelid',lid,
    [(i*2,i*2+1,i*2+3,i*2+2) for i in range(3)],[Dark]))
  mouth=[]
  for x,y,farX in [(112,293,68),(125,301,62),(138,306,57),
                    (165,306,49),(180,293,47)]:
    depth=(x+farX-320)/(2*(1536/16.8)*math.sin(math.radians(50)))
    width=2.0 if x in (112,180) else 4.0
    mouth.extend([tuple(reference_point((x,y-width),depth,origin,angle,HeadElevation)),
                  tuple(reference_point((x,y+width),depth,origin,angle,HeadElevation))])
  parts.append(mesh('Head · mouth',mouth,
    [(i*2,i*2+1,i*2+3,i*2+2) for i in range(4)],[Dark]))
  parts.append(mesh('Head · nostril',
    [tuple(reference_point(p,-.91,origin,angle,HeadElevation))
     for p in [(118,274),(125,263),(133,276)]],[(0,1,2)],[Dark]))
  return parts


def eye_patch(name, aperture, vertices, faces, angle, center, radius, mat):
  """Clip a measured pupil or glint in camera space and project onto its lens."""
  azimuth,elevation=math.radians(angle),math.radians(HeadElevation)
  def view(p):
    """Project a local point into the measured facial view in pixels."""
    x=math.cos(azimuth)*p.x-math.sin(azimuth)*p.y
    v=math.sin(elevation)*(math.sin(azimuth)*p.x+math.cos(azimuth)*p.y)
    v+=math.cos(elevation)*p.z
    return Vector((160+x*(1536/16.8),380-v*(1536/16.8)))
  direction=Matrix.Rotation(-azimuth,4,'Z') @ Vector((0,-math.cos(elevation),math.sin(elevation)))
  points=[Vector((center[0]+math.cos(Tau*i/48)*radius[0],
                  center[1]+math.sin(Tau*i/48)*radius[1])) for i in range(48)]
  contour=[view(Vector(p)) for p in vertices[:len(aperture)]]
  def cross(a,b):
    """Return the signed planar cross product."""
    return a.x*b.y-a.y*b.x
  orientation=1 if sum(cross(p,contour[(i+1)%len(contour)]) for i,p in enumerate(contour))>0 else -1
  for i,a in enumerate(contour):
    b=contour[(i+1)%len(contour)]
    clipped=[]
    for j,p in enumerate(points):
      previous=points[j-1]
      distance=orientation*cross(b-a,p-a)
      previousDistance=orientation*cross(b-a,previous-a)
      if (distance>=0)!=(previousDistance>=0):
        clipped.append(previous.lerp(p,previousDistance/(previousDistance-distance)))
      if distance>=0:
        clipped.append(p)
    points=clipped
  triangles=[]
  for face in faces:
    for i in range(1,len(face)-1):
      triangles.append([Vector(vertices[k]) for k in (face[0],face[i],face[i+1])])
  def project(p):
    """Interpolate a visible lens triangle at a measured pixel position."""
    for triangle in triangles:
      a,b,c=[view(q) for q in triangle]
      denominator=cross(b-a,c-a)
      if abs(denominator)<1e-9:
        continue
      u=cross(p-a,c-a)/denominator
      v=cross(b-a,p-a)/denominator
      if u>=-.0001 and v>=-.0001 and u+v<=1.0001:
        return triangle[0]*(1-u-v)+triangle[1]*u+triangle[2]*v+direction*.006
    raise ValueError('Eye detail outside its measured aperture.')
  middle=sum(points,Vector((0,0)))/len(points)
  patch=mesh(name,[tuple(project(p)) for p in points]+[tuple(project(middle))],
    [(len(points),i,(i+1)%len(points)) for i in range(len(points))],[mat])
  bm=bmesh.new()
  bm.from_mesh(patch.data)
  bmesh.ops.subdivide_edges(bm,edges=list(bm.edges),cuts=3,use_grid_fill=True)
  for vertex in bm.verts:
    vertex.co=project(view(vertex.co))
  bm.to_mesh(patch.data)
  bm.free()
  return patch


def wires(obj):
  """Show original face boundaries on the subdivided surface using face UVs."""
  wire = obj.copy()
  wire.data = obj.data
  wire.name = obj.name + ' · white edges'
  for slot in wire.material_slots:
    slot.link = 'OBJECT'
    slot.material = EdgeMaterial
  offset = wire.modifiers.new('Lift topology overlay', 'DISPLACE')
  offset.strength = .0018
  offset.mid_level = 0
  wire.visible_shadow = False
  wire.hide_viewport = True
  return wire


def edge_material():
  """Draw the coarse quad borders without subdivision or triangle diagonals."""
  mat = bpy.data.materials.new('Control edges · parametric quad boundaries')
  mat.use_nodes = True
  nodes, links = mat.node_tree.nodes, mat.node_tree.links
  nodes.clear()
  uv = nodes.new('ShaderNodeTexCoord')
  split = nodes.new('ShaderNodeSeparateXYZ')
  links.new(uv.outputs['UV'], split.inputs[0])
  borders = []
  for axis in ('X', 'Y'):
    low = nodes.new('ShaderNodeMath')
    low.operation = 'LESS_THAN'
    low.inputs[1].default_value = .012
    links.new(split.outputs[axis], low.inputs[0])
    high = nodes.new('ShaderNodeMath')
    high.operation = 'GREATER_THAN'
    high.inputs[1].default_value = .988
    links.new(split.outputs[axis], high.inputs[0])
    borders.extend([low.outputs[0], high.outputs[0]])
  previous = borders[0]
  for border in borders[1:]:
    maximum = nodes.new('ShaderNodeMath')
    maximum.operation = 'MAXIMUM'
    links.new(previous, maximum.inputs[0])
    links.new(border, maximum.inputs[1])
    previous = maximum.outputs[0]
  transparent = nodes.new('ShaderNodeBsdfTransparent')
  emission = nodes.new('ShaderNodeEmission')
  emission.inputs[0].default_value = (.94, .96, .88, 1)
  mix = nodes.new('ShaderNodeMixShader')
  links.new(previous, mix.inputs[0])
  links.new(transparent.outputs[0], mix.inputs[1])
  links.new(emission.outputs[0], mix.inputs[2])
  output = nodes.new('ShaderNodeOutputMaterial')
  links.new(mix.outputs[0], output.inputs[0])
  return mat


def smooth_form(obj):
  """Smooth the anatomical surface while retaining its editable control mesh."""
  bm = bmesh.new()
  bm.from_mesh(obj.data)
  crease = bm.edges.layers.float.get('crease_edge') or bm.edges.layers.float.new('crease_edge')
  socket = obj.data.attributes.get('Socket rim')
  for edge in bm.edges:
    # Keep the intentionally flat cut caps and eye opening rims readable.
    axis={'X':0,'Y':1}.get(obj.get('symmetry'))
    seam=axis is not None and all(abs(v.co[axis])<.00001 for v in edge.verts)
    if (edge.is_boundary or (socket and socket.data[edge.index].value)) and not seam:
      edge[crease] = 1.0 if obj.name.startswith('Head') else .8
    if seam:
      edge[crease] = 0
    if obj.name.startswith('Head') and all(
        vertex.co.y < -1.18 and 1.20 < vertex.co.z < 1.58 and
        abs(vertex.co.x) < .95 for vertex in edge.verts):
      edge[crease] = max(edge[crease], .45)
  bm.to_mesh(obj.data)
  bm.free()
  sub = obj.modifiers.new('Surface smoothing · control loops preserved', 'SUBSURF')
  sub.levels = 1
  sub.render_levels = sub.levels
  sub.uv_smooth = 'PRESERVE_BOUNDARIES'
  sub.show_only_control_edges = True


def fit_face(parts):
  """Attach traced lip and nostril vertices without moving their screen positions."""
  skin = parts[0]
  Stage.objects.link(skin)
  bpy.context.view_layer.update()
  evaluated = skin.evaluated_get(bpy.context.evaluated_depsgraph_get())
  elevation = math.radians(HeadElevation)
  direction = Matrix.Rotation(math.radians(-skin.get('referenceViewAngle',-50)), 4, 'Z') @ Vector(
    (0, -math.cos(elevation), math.sin(elevation)))
  for obj in parts:
    if obj.name not in ('Head · mouth', 'Head · nostril'):
      continue
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.subdivide_edges(bm, edges=list(bm.edges), cuts=5, use_grid_fill=True)
    bm.to_mesh(obj.data)
    bm.free()
    for vertex in obj.data.vertices:
      hit, location, normal, index = evaluated.ray_cast(
        vertex.co + direction * 10, -direction)
      if not hit:
        raise ValueError('Traced facial detail missed the skin.')
      vertex.co = location + direction * .012
  Stage.objects.unlink(skin)
  lens = next(obj for obj in parts if obj.name == 'Head · golden eye')
  Stage.objects.link(lens)
  bpy.context.view_layer.update()
  evaluated = lens.evaluated_get(bpy.context.evaluated_depsgraph_get())
  for obj in parts:
    if obj.name not in ('Head · pupil', 'Head · glint', 'Head · upper eyelid'):
      continue
    for vertex in obj.data.vertices:
      hit, location, normal, index = evaluated.ray_cast(
        vertex.co + direction * 10, -direction)
      if not hit:
        hit, location, normal, index = evaluated.closest_point_on_mesh(vertex.co)
      if not hit:
        raise ValueError('Eye detail missed its lens surface.')
      vertex.co = location + direction * (.04 if obj.name.endswith('upper eyelid') else .007)
  Stage.objects.unlink(lens)


def mirror(obj, axis):
  """Keep only one editable half and enforce welded bilateral symmetry."""
  bm = bmesh.new()
  bm.from_mesh(obj.data)
  normal = Vector((1, 0, 0) if axis == 0 else (0, 1, 0))
  bmesh.ops.bisect_plane(bm, geom=list(bm.verts) + list(bm.edges) + list(bm.faces),
                        plane_co=(0, 0, 0), plane_no=normal, dist=.00001,
                        clear_inner=True, clear_outer=False)
  for vertex in bm.verts:
    if abs(vertex.co[axis]) < .0001:
      vertex.co[axis] = 0
  bm.to_mesh(obj.data)
  bm.free()
  modifier = obj.modifiers.new('Bilateral symmetry · welded center', 'MIRROR')
  modifier.use_axis = (axis == 0, axis == 1, axis == 2)
  modifier.use_clip = True
  modifier.use_mirror_merge = True
  modifier.merge_threshold = .0001
  obj['symmetry'] = 'X' if axis == 0 else 'Y'


def put(parts, title, box, angle, floor, small=False):
  """Fit a linked view to its measured reference height and ground contact."""
  target = PartCollections[title]
  transform = Matrix.Rotation(math.radians(angle), 4, 'Z')
  if title == 'HEAD':
    transform = Matrix.Rotation(math.radians(HeadElevation-14),4,'X') @ transform
  elevation = math.radians(14)
  up = Vector((0, math.sin(elevation), math.cos(elevation)))
  coords = []
  for obj in parts:
    if obj.type != 'MESH':
      continue
    Stage.objects.link(obj)
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    data = evaluated.to_mesh()
    coords.extend(transform @ vertex.co for vertex in data.vertices)
    evaluated.to_mesh_clear()
    Stage.objects.unlink(obj)
  lowX, highX = min(v.x for v in coords), max(v.x for v in coords)
  lowV, highV = min(v.dot(up) for v in coords), max(v.dot(up) for v in coords)
  lowZ = min(v.z for v in coords)
  pixelScale = 1536 / 16.8
  scale = (box[3] - box[1]) / pixelScale / (highV - lowV)
  targetX = ((box[0] + box[2]) / 2 - 768) / pixelScale
  targetBottom = (512 - box[3]) / pixelScale
  z = floor - lowZ * scale
  y = (targetBottom - lowV * scale - math.cos(elevation) * z) / math.sin(elevation)
  origin = Vector((targetX - (lowX + highX) / 2 * scale, y, z))
  if title == 'HEAD' and not small:
    scale=1.0
    z=floor-lowZ
    y=((512-380)/pixelScale-math.cos(elevation)*z)/math.sin(elevation)
    origin=Vector(((160-768)/pixelScale,y,z))
  label = 'small' if small else 'large'
  for original in parts:
    obj = original.copy()
    obj.data = original.data
    obj.name = original.name + ' · ' + label
    obj.matrix_world = Matrix.Translation(origin) @ transform @ Matrix.Scale(scale, 4)
    target.objects.link(obj)
    obj['part'] = title
    obj['view'] = label
    obj['referenceBounds'] = list(box)
    if obj.type == 'MESH' and 'topology' in original:
      obj.show_wire = True
      obj.show_all_edges = True
      wire = wires(original)
      wire.matrix_world = obj.matrix_world.copy()
      WireCollection.objects.link(wire)
  width = (highX - lowX) * scale * pixelScale
  print(title, label, 'width', round(width,1), 'target', box[2] - box[0])
  return origin


def text_label(label, point, size=.21):
  """Add a restrained camera-facing label to a diagram panel."""
  data = bpy.data.curves.new(label, 'FONT')
  data.body = label
  data.size = size
  data.align_x = 'CENTER'
  data.align_y = 'CENTER'
  data.space_character = 1.15
  data.materials.append(Ink)
  obj = bpy.data.objects.new(label + ' · label', data)
  obj.location = point
  obj.rotation_euler = Camera.rotation_euler
  Stage.objects.link(obj)


def area(name, position, energy, size, target):
  """Create a large softbox facing the modeling stage."""
  data = bpy.data.lights.new(name, 'AREA')
  data.energy = energy
  data.shape = 'DISK'
  data.size = size
  obj = bpy.data.objects.new(name, data)
  obj.location = position
  obj.rotation_euler = (Vector(target) - obj.location).to_track_quat('-Z', 'Y').to_euler()
  Stage.objects.link(obj)


def setup_stage():
  """Set up a single camera framing six separated anatomical study panels."""
  global Camera
  scene = bpy.context.scene
  scene.render.engine = 'CYCLES'
  scene.cycles.samples = 32
  scene.cycles.use_denoising = True
  scene.cycles.max_bounces = 5
  scene.render.resolution_x = 1536
  scene.render.resolution_y = 1024
  scene.render.resolution_percentage = 100
  scene.render.image_settings.file_format = 'PNG'
  scene.view_settings.view_transform = 'Standard'
  scene.view_settings.exposure = .12
  scene.world = bpy.data.worlds.new('Neutral studio world')
  scene.world.color = (.35, .35, .35)
  scene.world.use_nodes = True
  nodes = scene.world.node_tree.nodes
  links = scene.world.node_tree.links
  environment = nodes['Background']
  environment.inputs[0].default_value = (.74, .78, .85, 1)
  environment.inputs[1].default_value = .38
  backdrop = nodes.new('ShaderNodeBackground')
  backdrop.inputs[0].default_value = (.46, .49, .50, 1)
  path = nodes.new('ShaderNodeLightPath')
  mix = nodes.new('ShaderNodeMixShader')
  links.new(path.outputs['Is Camera Ray'], mix.inputs[0])
  links.new(environment.outputs[0], mix.inputs[1])
  links.new(backdrop.outputs[0], mix.inputs[2])
  links.new(mix.outputs[0], nodes['World Output'].inputs['Surface'])
  elevation = math.radians(14)
  up = Vector((0, math.sin(elevation), math.cos(elevation)))
  normal = Vector((0, -math.cos(elevation), math.sin(elevation)))
  cameraData = bpy.data.cameras.new('Parts sheet · orthographic')
  cameraData.type = 'ORTHO'
  cameraData.ortho_scale = 16.8
  Camera = bpy.data.objects.new('Parts sheet · camera', cameraData)
  Camera.location = normal * 35
  Camera.rotation_euler = (-normal).to_track_quat('-Z', 'Y').to_euler()
  Stage.objects.link(Camera)
  scene.camera = Camera
  grid = [
    ('HEAD', head, -50, -59, (17,127,301,376), (319,187,490,340)),
    ('BODY', body, -25, -80, (537,66,836,410), (858,163,1004,397)),
    ('TAIL', tail, 10, 30, (1044,77,1370,401), (1348,216,1520,409)),
    ('ARM', arm, 0, 0, (44,554,277,884), (303,606,476,846)),
    ('LEG', leg, 0, 0, (567,528,798,916), (835,631,987,891)),
    ('FOOT', foot, -19, -45, (1052,726,1286,903), (1320,783,1507,896))]
  for index, (title, build, angle, smallAngle, bounds, smallBounds) in enumerate(grid):
    x = ((index % 3) - 1) * 5.6
    centerY = 251 if index < 3 else 763
    y = (512 - centerY) / (1536 / 16.8)
    cell = Vector((x, 0, 0)) + up * (y - 1.50)
    parts = build()
    if title in ('HEAD', 'BODY', 'TAIL', 'FOOT'):
      mirror(parts[0], 1 if title == 'TAIL' else 0)
    smooth_form(parts[0])
    if title == 'HEAD':
      fit_face(parts)
      for detail in parts[1:]:
        mirror(detail, 0)
    put(parts, title, bounds, angle, cell.z)
    smallParts = {'ARM':arm_small,'LEG':leg_small,'BODY':body_small}[title]() if title in ('ARM','LEG','BODY') else parts
    if smallParts is not parts:
      if title == 'BODY':
        mirror(smallParts[0],0)
      smooth_form(smallParts[0])
      smallParts[0]['variant']='small anatomical variant'
    put(smallParts, title, smallBounds, smallAngle, cell.z, True)
    ground = mesh(title + ' · ground',
      [(-2.78,-8,-.035),(2.78,-8,-.035),(2.78,8,-.035),(-2.78,8,-.035)],
      [(0,1,2,3)], [Grey], smooth=False)
    ground.location = cell
    Stage.objects.link(ground)
    labelY = 462 if index < 3 else 960
    text_label(title, Vector((x,0,0)) + up * ((512-labelY)/(1536/16.8)) + normal*30,
               .30)
  keyData = bpy.data.lights.new('Large studio key', 'SUN')
  keyData.energy = 2.2
  keyData.angle = 1.0
  key = bpy.data.objects.new('Large studio key', keyData)
  key.rotation_euler = Vector((6, 4, -6)).to_track_quat('-Z', 'Y').to_euler()
  Stage.objects.link(key)
  area('Soft studio fill', (4, -10, 6), 600, 12, (0, 0, 0))
  for x in (-2.8, 2.8):
    line = curve('Vertical divider', [Vector((x, 0, 0)) - up * 5.6 + normal * 6,
                                    Vector((x, 0, 0)) + up * 5.6 + normal * 6], .011, Wire)
    Stage.objects.link(line)
  line = curve('Horizontal divider', [Vector((-8.4, 0, 0)) + normal * 6,
                                      Vector((8.4, 0, 0)) + normal * 6], .011, Wire)
  Stage.objects.link(line)
  return scene


def validate():
  """Audit every distinct anatomical cage and save its topology inventory."""
  report = []
  seen = set()
  for name, group in PartCollections.items():
    for obj in group.objects:
      if obj.type != 'MESH' or 'topology' not in obj or obj.data.name in seen:
        continue
      seen.add(obj.data.name)
      bm = bmesh.new()
      smooth = obj.modifiers.get('Surface smoothing · control loops preserved')
      smooth.show_viewport = False
      bpy.context.view_layer.update()
      evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
      evaluatedMesh = evaluated.to_mesh()
      bm.from_mesh(evaluatedMesh)
      boundary = sum(edge.is_boundary for edge in bm.edges)
      nonmanifold = sum(not edge.is_manifold and not edge.is_boundary for edge in bm.edges)
      assert nonmanifold == 0, (name, nonmanifold)
      assert boundary == obj.get('eyeBoundaryEdges', 0), (name, boundary)
      assert all(face.calc_area() > 1e-8 for face in bm.faces), name
      report.append(dict(part=name, variant=obj['view'], vertices=len(bm.verts),
                         faces=len(bm.faces),
                         quads=sum(len(face.verts) == 4 for face in bm.faces),
                         triangles=sum(len(face.verts) == 3 for face in bm.faces),
                         boundaryEdges=boundary,
                         sharedSmallView=name not in ('ARM','LEG','BODY'),
                         mirrorAxis=obj.get('symmetry')))
      bm.free()
      evaluated.to_mesh_clear()
      smooth.show_viewport = True
  assert len(report) == 9
  (Root / 'source/topology.json').write_text(json.dumps(report, indent=2) + '\n')
  print(json.dumps(report, indent=2))


def panel_studios(scene):
  """Render the linked grid parts in seamless studio tiles inside Blender."""
  tree = bpy.data.node_groups.new('Six live studio panels', 'CompositorNodeTree')
  tree.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
  scene.compositing_node_group = tree
  nodes, links = tree.nodes, tree.links
  output = nodes.new('NodeGroupOutput')
  percentage = scene.render.resolution_percentage
  canvas = bpy.data.images.new('Parts sheet · canvas',
                              width=int(1536 * percentage / 100),
                              height=int(1024 * percentage / 100))
  canvas.generated_color = (.96, .96, .96, 1)
  background = nodes.new('CompositorNodeImage')
  background.image = canvas
  previous = background.outputs['Image']
  elevation = math.radians(14)
  up = Vector((0, math.sin(elevation), math.cos(elevation)))
  for index, title in enumerate(PartCollections):
    panel = bpy.data.scenes.new(title + ' · isolated studio')
    panel.world = scene.world
    panel.render.engine = 'CYCLES'
    panel.cycles.samples = scene.cycles.samples
    panel.cycles.use_denoising = True
    panel.cycles.max_bounces = 5
    panel.render.resolution_x = scene.render.resolution_x
    panel.render.resolution_y = scene.render.resolution_y
    panel.render.resolution_percentage = percentage
    panel.render.use_border = False
    panel.render.use_crop_to_border = False
    panel.render.border_min_x = 1 / 3 + .0006
    panel.render.border_max_x = 2 / 3 - .0006
    panel.render.border_min_y = .25 + .0008
    panel.render.border_max_y = .75 - .0008
    panel.view_settings.view_transform = scene.view_settings.view_transform
    panel.view_settings.exposure = scene.view_settings.exposure
    panel.collection.children.link(PartCollections[title])
    for obj in WireCollection.objects:
      if obj.get('part') == title:
        panel.collection.objects.link(obj)
    for obj in Stage.objects:
      if obj.type == 'LIGHT' or obj.name == title + ' · label':
        panel.collection.objects.link(obj)
    camera = Camera.copy()
    camera.data = Camera.data.copy()
    camera.data.ortho_scale = 16.8
    x = ((index % 3) - 1) * 5.6
    centerY = 251 if index < 3 else 763
    y = (512-centerY)/(1536/16.8)
    center = Vector((x, 0, 0)) + up * y
    camera.location += center
    panel.collection.objects.link(camera)
    panel.camera = camera
    floor = mesh(title + ' · seamless floor',
      [(-60, -60, 0), (60, -60, 0), (60, 60, 0), (-60, 60, 0)],
      [(0, 1, 2, 3)], [Grey], smooth=False)
    floor.location = center - up * 1.5 + Vector((0, 0, -.035))
    floor.is_shadow_catcher=True
    panel.render.film_transparent=True
    panel.collection.objects.link(floor)
    render = nodes.new('CompositorNodeRLayers')
    render.scene = panel
    render.label = title
    backdrop=nodes.new('CompositorNodeRGB')
    backdrop.outputs[0].default_value=tuple(linear(v/255)/(2**scene.view_settings.exposure) for v in (219,222,226))+(1,)
    studio=nodes.new('CompositorNodeAlphaOver')
    links.new(backdrop.outputs[0],studio.inputs['Background'])
    links.new(render.outputs['Image'],studio.inputs['Foreground'])
    mask = nodes.new('CompositorNodeBoxMask')
    mask.inputs['Position'].default_value = (.5, .5)
    mask.inputs['Size'].default_value = (1 / 3 - .0012,
      (502 if index < 3 else 522)/1536 - .0012)
    alpha = nodes.new('CompositorNodeSetAlpha')
    links.new(studio.outputs['Image'], alpha.inputs['Image'])
    links.new(mask.outputs[0], alpha.inputs['Alpha'])
    transform = nodes.new('CompositorNodeTransform')
    links.new(alpha.outputs['Image'], transform.inputs['Image'])
    transform.inputs['X'].default_value = ((index % 3) - 1) * 512 * percentage / 100
    transform.inputs['Y'].default_value = (261 if index < 3 else -251) * percentage / 100
    transform.inputs['Scale'].default_value = 1
    over = nodes.new('CompositorNodeAlphaOver')
    links.new(previous, over.inputs['Background'])
    links.new(transform.outputs['Image'], over.inputs['Foreground'])
    previous = over.outputs['Image']
    render.location = (-800, -index * 220)
    transform.location = (-570, -index * 220)
    over.location = (-320 + index * 200, 200)
  links.new(previous, output.inputs['Image'])
  output.location = (1000, 200)


def main():
  """Rebuild, validate and save the source scene and requested render variants."""
  global Green, Yellow, Gold, Dark, White, Wire, Grey, Ink, EdgeMaterial, Brow
  global Stage, WireCollection, PartCollections
  parser = argparse.ArgumentParser()
  parser.add_argument('--preview', action='store_true')
  args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
  bpy.ops.wm.read_factory_settings(use_empty=True)
  Green = material('Skin · leaf green', '75A65A')
  Brow = material('Brow · green shadow', '547737')
  Yellow = material('Belly · warm butter yellow', 'F4CF6D')
  studio_tint(Green, (.22,.40,.43))
  studio_tint(Yellow, (.46,.44,.39))
  Gold = material('Eyes · amber gold', 'FFCF2D', .22)
  eyeShader = Gold.node_tree.nodes.get('Principled BSDF')
  eyeShader.inputs['Specular IOR Level'].default_value = .48
  Dark = material('Face · charcoal green', '172A22', .5)
  White = material('Eye glints', 'FFFFED', .25, True)
  Wire = material('Topology · ivory white', 'F5F5E8', .8, True)
  EdgeMaterial = edge_material()
  Grey = material('Stage · light neutral grey', 'E4E5E6', 1)
  Ink = material('Labels · slate grey', '575C60', 1, True)
  Stage = collection('STUDIO · camera lights labels and tiles')
  WireCollection = collection('WIREFRAME · toggle for shaded view')
  PartCollections = {name: collection(name + ' · editable parts')
                     for name in ('HEAD', 'BODY', 'TAIL', 'ARM', 'LEG', 'FOOT')}
  scene = setup_stage()
  validate()
  scene['description'] = 'Six separate editable quad-mesh anatomical studies. Head, body, tail and foot use mirrored meshes. Body, arm and leg include separately authored small variants.'
  scene['reference'] = 'User-provided six-panel wireframe shape sheet, 2026-09-24. Reference bitmap is not included.'
  for screen in bpy.data.screens:
    for areaItem in screen.areas:
      if areaItem.type == 'VIEW_3D':
        space = areaItem.spaces.active
        space.region_3d.view_perspective = 'CAMERA'
        space.shading.color_type = 'MATERIAL'
        space.overlay.show_extras = False
        space.overlay.show_floor = False
        space.overlay.show_axis_x = False
        space.overlay.show_axis_y = False
  bpy.ops.object.select_all(action='DESELECT')
  active = next(o for o in PartCollections['HEAD'].objects if 'ocular' in o.name and 'large' in o.name)
  active.select_set(True)
  bpy.context.view_layer.objects.active = active
  if args.preview:
    scene.render.resolution_percentage = 75
    scene.cycles.samples = 16
  for obj in WireCollection.objects:
    for title in PartCollections:
      if obj.name.startswith(title.title() + ' ·'):
        obj['part'] = title
  panel_studios(scene)
  for obj in list(bpy.data.objects):
    if not obj.users_collection:
      bpy.data.objects.remove(obj)
  bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=False, do_recursive=True)
  scene.render.filepath = str(Root / 'renders/parts_wireframe.png')
  bpy.ops.wm.save_as_mainfile(filepath=str(Root / 'source/parts_study.blend'))
  bpy.ops.render.render(write_still=True)
  if not args.preview:
    for obj in WireCollection.objects:
      obj.hide_render = True
    scene.render.filepath = str(Root / 'renders/parts_shaded.png')
    bpy.ops.render.render(write_still=True)
    for obj in WireCollection.objects:
      obj.hide_render = False
    scene.render.filepath = str(Root / 'renders/parts_wireframe.png')
    bpy.ops.wm.save_as_mainfile(filepath=str(Root / 'source/parts_study.blend'))


if __name__ == '__main__':
  main()
