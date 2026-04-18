#!/usr/bin/env python3
"""
CSS Color to OKLCH converter.
Scans CSS/SCSS/SASS files and converts hex, rgb, rgba, hsl, hsla to OKLCH.

Usage:
  python convert_to_oklch.py styles.css                    # Single file
  python convert_to_oklch.py /path/to/folder               # All CSS files in folder
  python convert_to_oklch.py /path/to/folder --dry-run     # Preview changes
"""

import sys
import os
import re
from pathlib import Path

try:
    from coloraide import Color
except ImportError:
    print("coloraide not installed. Run: pip install coloraide --break-system-packages")
    sys.exit(1)

SUPPORTED_EXTENSIONS = {'.css', '.scss', '.sass', '.less', '.styl', '.pcss', '.postcss'}

# Regex patterns for color formats
PATTERNS = {
    # Hex: #fff, #ffffff, #ffffffff (with alpha)
    'hex': re.compile(r'#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b'),
    # rgb() and rgba()
    'rgb': re.compile(r'rgba?\(\s*[\d.]+%?\s*[,\s]\s*[\d.]+%?\s*[,\s]\s*[\d.]+%?\s*(?:[,/]\s*[\d.]+%?)?\s*\)'),
    # hsl() and hsla()
    'hsl': re.compile(r'hsla?\(\s*[\d.]+(?:deg|rad|grad|turn)?\s*[,\s]\s*[\d.]+%?\s*[,\s]\s*[\d.]+%?\s*(?:[,/]\s*[\d.]+%?)?\s*\)'),
}

# Combined pattern
COLOR_PATTERN = re.compile(
    r'(' + '|'.join(p.pattern for p in PATTERNS.values()) + r')',
    re.IGNORECASE
)

def convert_color_to_oklch(color_str: str) -> tuple[str, bool]:
    """
    Convert a color string to OKLCH format.
    Returns (oklch_string, success).
    """
    try:
        color_str = color_str.strip()
        
        # Parse the color
        c = Color(color_str)
        
        # Convert to OKLCH
        oklch = c.convert('oklch')
        
        # Extract components
        l = oklch['lightness']  # 0-1
        c_val = oklch['chroma']  # 0-0.4+
        h = oklch['hue']  # 0-360 (can be NaN for achromatic)
        alpha = oklch.alpha()
        
        # Format OKLCH - be precise but clean up tiny values
        # L is percentage, C is decimal, H is degrees
        l_pct = l * 100
        
        # Clean up tiny floating point errors
        if c_val < 1e-10:
            c_val = 0
        
        # Handle achromatic colors (no hue)
        import math
        if math.isnan(h) or c_val == 0:
            h_str = "0"
        else:
            h_str = f"{h}"
        
        # Format chroma - avoid scientific notation
        c_str = f"{c_val}" if c_val >= 0.0001 else "0"
        
        if alpha is not None and alpha < 1:
            oklch_str = f"oklch({l_pct}% {c_str} {h_str} / {alpha})"
        else:
            oklch_str = f"oklch({l_pct}% {c_str} {h_str})"
        
        return oklch_str, True
        
    except Exception as e:
        return color_str, False

def process_css_content(content: str) -> tuple[str, int]:
    """
    Process CSS content and convert all colors to OKLCH.
    Returns (new_content, conversion_count).
    """
    conversions = 0
    
    def replace_color(match):
        nonlocal conversions
        original = match.group(0)
        
        # Skip if already oklch
        if original.lower().startswith('oklch'):
            return original
        
        oklch_str, success = convert_color_to_oklch(original)
        
        if success and oklch_str != original:
            conversions += 1
            # Return OKLCH with original as comment after
            return f"{oklch_str} /* {original} */"
        
        return original
    
    new_content = COLOR_PATTERN.sub(replace_color, content)
    return new_content, conversions

def process_file(file_path: Path, dry_run: bool = False) -> int:
    """Process a single file. Returns number of conversions."""
    try:
        content = file_path.read_text(encoding='utf-8')
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return 0
    
    new_content, conversions = process_css_content(content)
    
    if conversions > 0:
        if dry_run:
            print(f"{file_path}: {conversions} colors would be converted")
        else:
            file_path.write_text(new_content, encoding='utf-8')
            print(f"{file_path}: {conversions} colors converted")
    
    return conversions

def process_folder(folder_path: Path, dry_run: bool = False) -> tuple[int, int]:
    """
    Process all CSS files in folder recursively.
    Returns (files_processed, total_conversions).
    """
    files_processed = 0
    total_conversions = 0
    
    for ext in SUPPORTED_EXTENSIONS:
        for file_path in folder_path.rglob(f'*{ext}'):
            conversions = process_file(file_path, dry_run)
            if conversions > 0:
                files_processed += 1
                total_conversions += conversions
    
    return files_processed, total_conversions

def main():
    args = sys.argv[1:]
    dry_run = '--dry-run' in args
    if dry_run:
        args.remove('--dry-run')
    
    if not args:
        print(__doc__)
        sys.exit(1)
    
    input_path = Path(args[0])
    
    if input_path.is_dir():
        files, conversions = process_folder(input_path, dry_run)
        action = "would be" if dry_run else "were"
        print(f"\n{conversions} colors {action} converted in {files} files")
    elif input_path.is_file():
        conversions = process_file(input_path, dry_run)
        if conversions == 0:
            print("No colors to convert")
    else:
        print(f"Error: {input_path} not found")
        sys.exit(1)

if __name__ == '__main__':
    main()
