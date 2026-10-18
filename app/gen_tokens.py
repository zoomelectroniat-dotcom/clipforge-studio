"""Generate static/css/tokens.css from replica/tokens.json (clean-room design tokens)."""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOKENS = ROOT / "replica" / "tokens.json"
OUT = pathlib.Path(__file__).resolve().parent / "static" / "css" / "tokens.css"


def flatten(prefix, obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            flatten(f"{prefix}-{k}" if prefix else k, v, out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out[f"{prefix}-{i}"] = v
    else:
        out[prefix] = obj


def main():
    tokens = json.loads(TOKENS.read_text())
    lines = [":root {"]
    # colors
    cmap = {}
    flatten("color", tokens["color"], cmap)
    for k, v in cmap.items():
        lines.append(f"  --{k}: {v};")
    # fonts
    lines.append(f"  --font-sans: {tokens['font']['sans']};")
    lines.append(f"  --font-mono: {tokens['font']['mono']};")
    # type scale
    for name, spec in tokens["type"].items():
        lines.append(f"  --type-{name}-size: {spec['size']}px;")
        lines.append(f"  --type-{name}-line: {spec['line']}px;")
        lines.append(f"  --type-{name}-weight: {spec['weight']};")
    # spacing: both --space-<value> and --space-i-<index>
    for i, v in enumerate(tokens["space"]):
        lines.append(f"  --space-{v}: {v}px;")
        lines.append(f"  --space-i-{i}: {v}px;")
    # radius / shadow / motion / layout
    for name, v in tokens["radius"].items():
        lines.append(f"  --radius-{name}: {v}px;")
    for name, v in tokens["shadow"].items():
        lines.append(f"  --shadow-{name}: {v};")
    lines.append(f"  --motion-fast: {tokens['motion']['fast']};")
    lines.append(f"  --motion-base: {tokens['motion']['base']};")
    lines.append(f"  --motion-ease: {tokens['motion']['ease']};")
    lines.append(f"  --layout-max-content: {tokens['layout']['max-content']}px;")
    lines.append(f"  --layout-sidebar: {tokens['layout']['sidebar']}px;")
    lines.append(f"  --layout-sidebar-collapsed: {tokens['layout']['sidebar-collapsed']}px;")
    lines.append(f"  --layout-header: {tokens['layout']['header']}px;")
    lines.append("}")
    lines.append("")
    lines.append("@media (prefers-reduced-motion: reduce) {")
    lines.append("  *, *::before, *::after { transition: none !important; animation: none !important; }")
    lines.append("}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines))
    print(f"wrote {OUT} ({len(lines)} lines)")


if __name__ == "__main__":
    main()
