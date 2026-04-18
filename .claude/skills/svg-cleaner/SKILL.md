---
name: svg-cleaner
description: Clean and optimize SVG files by converting borders to paths, merging paths, removing backgrounds, applying currentColor for flexible theming, and optimizing with SVGO. Supports batch processing folders to clean multiple SVGs and generate sprite files. Use when users need to clean up SVG logos or icons, extract specific elements from SVGs, process entire icon sets, or prepare SVGs for production use.
---

# SVG Cleaner

## Workflow

### Single File
1. **Read SVG**: `view /path/to/file.svg`
2. **Merge paths**: Concatenate all `<path d="...">` attributes with spaces
3. **Remove background**: Delete `<clipPath>`, `<rect>` backgrounds, empty `<defs>`
4. **Apply currentColor**: Replace fill colors with `fill="currentColor"`
5. **Optimize**: Use SVGO or manual optimization

### Batch Folder Processing
When input is a folder path:
1. Find all `.svg` files in folder
2. Clean each SVG (merge, remove background, currentColor)
3. Save cleaned versions as `filename-cc.svg`
4. Create sprite combining all as `foldername-sprite-cc.svg`

**Sprite structure:**
```xml
<svg xmlns="http://www.w3.org/2000/svg">
  <symbol id="icon-name" viewBox="0 0 W H">
    <path fill="currentColor" d="..."/>
  </symbol>
  <!-- repeat for each SVG -->
</svg>
```

Symbol IDs derived from original filenames (e.g., `logo.svg` → `id="logo"`)

## Optimization

**Preferred - SVGO:**
```bash
npx -y svgo@latest input.svg -o output.svg --multipass
```

**Fallback (if SVGO unavailable):**
```python
import re

with open('input.svg', 'r') as f:
    svg = f.read()

# Round decimals to 1-2 places
svg = re.sub(r'(\d+\.\d{2})\d+', r'\1', svg)

# Remove unnecessary spaces
svg = re.sub(r'\s+', ' ', svg)
svg = re.sub(r'>\s+<', '><', svg)

# Minify to single line
svg = svg.replace('\n', '')

with open('output.svg', 'w') as f:
    f.write(svg)
```

## Element Extraction

To extract specific elements (e.g., single letter):
1. Copy only target path elements
2. Adjust viewBox to crop bounds
3. Optimize

## Outputs

**Single file:**
- Clean version (merged, no background)
- currentColor version
- Optimized version

**Batch folder:**
- Individual cleaned SVGs: `filename-cc.svg`
- Combined sprite: `foldername-sprite-cc.svg`
- Optionally: optimized versions of all
