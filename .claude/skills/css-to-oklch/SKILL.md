---
name: css-to-oklch
description: Convert CSS colors (hex, rgb, rgba, hsl, hsla) to OKLCH format. Scans CSS/SCSS/SASS/Less files and replaces colors while preserving originals as comments. Use when users want to modernize CSS color definitions or migrate to OKLCH color space.
---

# CSS to OKLCH

## Workflow

1. Scan target files (CSS, SCSS, SASS, Less, PostCSS)
2. Detect colors: `#hex`, `rgb()`, `rgba()`, `hsl()`, `hsla()`
3. Convert to OKLCH
4. Replace with `oklch()` + original as comment

## Output Format

```css
/* Before */
--primary: #ff0000;

/* After */
--primary: oklch(62.79%...29.23) /* #ff0000 */;
```

## Usage

**Python script (bundled fallback):**
```bash
# Requires: pip install coloraide --break-system-packages

# Single file
python scripts/convert_to_oklch.py styles.css

# Entire project
python scripts/convert_to_oklch.py /path/to/folder

# Preview changes without modifying
python scripts/convert_to_oklch.py /path/to/folder --dry-run
```

## Supported Files

`.css`, `.scss`, `.sass`, `.less`, `.styl`, `.pcss`, `.postcss`

## Notes

- CSS variables are converted like any other color
- Alpha values preserved (`rgba()` → `oklch(... / alpha)`)
- Very small chroma values cleaned to 0 (avoids scientific notation)
- Original color preserved as comment for reference/rollback
