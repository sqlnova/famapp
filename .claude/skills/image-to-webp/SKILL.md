---
name: image-to-webp
description: Convert and optimize images to WebP format. Supports PNG, JPG, GIF, TIFF, BMP. Handles single files or batch folder processing. Use when users need to optimize images for web, convert images to WebP, or batch process image folders.
---

# Image to WebP

## Workflow

### Single File
```bash
# Preferred - sharp (Node.js)
npx -y sharp-cli --input image.png --output image.webp --quality 85

# Alternative - cwebp
cwebp -q 85 image.png -o image.webp
```

### Batch Folder
```bash
# Process all images in folder
for f in /path/to/folder/*.{png,jpg,jpeg}; do
  npx -y sharp-cli --input "$f" --output "${f%.*}.webp" --quality 85
done
```

## Fallback Script

If sharp/cwebp unavailable, use bundled Python script:

```bash
# Requires: pip install Pillow --break-system-packages

# Single file
python scripts/convert_to_webp.py image.png

# Batch folder
python scripts/convert_to_webp.py /path/to/folder

# Custom quality (default: 85)
python scripts/convert_to_webp.py image.png --quality 90
```

## Options

| Quality | Use Case |
|---------|----------|
| 75-80   | Maximum compression, acceptable quality |
| 85      | Balanced (default) |
| 90-95   | High quality, larger files |

## Supported Formats

PNG, JPG, JPEG, GIF, TIFF, BMP → WebP

## Output

- Single file: `filename.webp`
- Batch folder: Each image converted to `.webp` alongside original
- Reports size reduction percentage for each file
