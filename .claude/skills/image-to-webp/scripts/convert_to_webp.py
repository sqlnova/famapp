#!/usr/bin/env python3
"""
WebP image converter using Pillow.
Fallback for when sharp/cwebp are unavailable.

Usage:
  python convert_to_webp.py input.png                    # Single file
  python convert_to_webp.py input.png output.webp        # Custom output
  python convert_to_webp.py /path/to/folder              # Batch folder
  python convert_to_webp.py input.png --quality 90       # Custom quality
"""

import sys
import os
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Pillow not installed. Run: pip install Pillow --break-system-packages")
    sys.exit(1)

SUPPORTED_FORMATS = {'.png', '.jpg', '.jpeg', '.gif', '.tiff', '.tif', '.bmp'}
DEFAULT_QUALITY = 85

def convert_to_webp(input_path: Path, output_path: Path = None, quality: int = DEFAULT_QUALITY):
    """Convert a single image to WebP format."""
    if output_path is None:
        output_path = input_path.with_suffix('.webp')
    
    with Image.open(input_path) as img:
        # Handle transparency for formats that support it
        if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
            img.save(output_path, 'WEBP', quality=quality, lossless=False)
        else:
            img = img.convert('RGB')
            img.save(output_path, 'WEBP', quality=quality, lossless=False)
    
    # Report size reduction
    orig_size = input_path.stat().st_size
    new_size = output_path.stat().st_size
    reduction = (1 - new_size / orig_size) * 100
    print(f"{input_path.name} → {output_path.name} ({reduction:.1f}% smaller)")
    return output_path

def process_folder(folder_path: Path, quality: int = DEFAULT_QUALITY):
    """Process all supported images in a folder."""
    converted = []
    for file in folder_path.iterdir():
        if file.suffix.lower() in SUPPORTED_FORMATS:
            try:
                result = convert_to_webp(file, quality=quality)
                converted.append(result)
            except Exception as e:
                print(f"Error converting {file.name}: {e}")
    return converted

def main():
    args = sys.argv[1:]
    quality = DEFAULT_QUALITY
    
    # Parse --quality flag
    if '--quality' in args:
        idx = args.index('--quality')
        quality = int(args[idx + 1])
        args = args[:idx] + args[idx + 2:]
    
    if not args:
        print(__doc__)
        sys.exit(1)
    
    input_path = Path(args[0])
    
    if input_path.is_dir():
        results = process_folder(input_path, quality)
        print(f"\nConverted {len(results)} images")
    elif input_path.is_file():
        output_path = Path(args[1]) if len(args) > 1 else None
        convert_to_webp(input_path, output_path, quality)
    else:
        print(f"Error: {input_path} not found")
        sys.exit(1)

if __name__ == '__main__':
    main()
