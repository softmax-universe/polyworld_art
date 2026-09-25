"""Compare Blender renders with a user-supplied diagram without bundling it."""
import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


def silhouette(image):
  """Extract colored forms and fill their white topology lines for comparison."""
  mask = Image.new('L', image.size)
  pixels = image.tobytes()
  colors = [pixels[i:i+3] for i in range(0,len(pixels),3)]
  mask.putdata([255 if max(r,g,b)-min(r,g,b)>30 and g>b*1.15
                and max(r,g,b)>70 else 0 for r,g,b in colors])
  mask = mask.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.MinFilter(7))
  ImageDraw.floodfill(mask, (0,0), 127)
  return mask.point(lambda value: 0 if value == 127 else 255)


def main():
  """Write an exact 50% overlay, a side-by-side sheet and silhouette metrics."""
  parser = argparse.ArgumentParser()
  parser.add_argument('reference', type=Path)
  parser.add_argument('render', type=Path)
  parser.add_argument('output', type=Path)
  parser.add_argument('--before', type=Path)
  args = parser.parse_args()
  args.output.mkdir(parents=True, exist_ok=True)
  reference = Image.open(args.reference).convert('RGB')
  render = Image.open(args.render).convert('RGB').resize(reference.size, Image.Resampling.LANCZOS)
  Image.blend(render, reference, .5).save(args.output/'overlay_50.png')
  sheet = Image.new('RGB', (reference.width*2, reference.height), 'white')
  sheet.paste(reference, (0,0))
  sheet.paste(render, (reference.width,0))
  sheet.save(args.output/'reference_and_render.png')
  refMask = silhouette(reference)
  images = {'revised': render}
  if args.before:
    images['before'] = Image.open(args.before).convert('RGB').resize(reference.size, Image.Resampling.LANCZOS)
  report = {'method': 'Colored silhouette intersection over union per panel. Measures outlines and placement, not topology or anatomical quality.', 'panels': {}}
  titles = ['HEAD','BODY','TAIL','ARM','LEG','FOOT']
  for version, image in images.items():
    mask = silhouette(image)
    for i,title in enumerate(titles):
      box = ((i%3)*512, 0 if i<3 else 502, (i%3+1)*512, 502 if i<3 else 1024)
      a,b = refMask.crop(box).tobytes(),mask.crop(box).tobytes()
      intersection = sum(bool(x) and bool(y) for x,y in zip(a,b))
      union = sum(bool(x) or bool(y) for x,y in zip(a,b))
      report['panels'].setdefault(title,{})[version] = round(intersection/union,4)
  (args.output/'comparison.json').write_text(json.dumps(report,indent=2)+'\n')
  print(json.dumps(report,indent=2))


if __name__ == '__main__':
  main()
