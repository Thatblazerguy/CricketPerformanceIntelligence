#!/usr/bin/env python3
"""
scripts/check_links.py
Validates relative markdown links across README.md and docs/*.md.
Stdlib only.
"""
import glob
import os
import re
import sys
from pathlib import Path

# Match standard markdown links: [text](target)
# Exclude images ! [text](target) if target is external, but check local assets
LINK_PATTERN = re.compile(r'(?<!!)\[([^\]]+)\]\(([^)]+)\)')
IMAGE_PATTERN = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')

def slugify_heading(heading: str) -> str:
    """Convert heading text to GitHub-style markdown anchor."""
    # Strip markdown bold/italic/code formatting inside heading
    cleaned = re.sub(r'[*_`]', '', heading.strip())
    # Remove emojis or non-alphanumeric except spaces, hyphens, underscores
    # GitHub lowercase
    cleaned = cleaned.lower()
    # Replace spaces with hyphens
    cleaned = re.sub(r'\s+', '-', cleaned)
    # Remove chars that are not alphanumeric, hyphen, or underscore
    cleaned = re.sub(r'[^\w\-]', '', cleaned)
    return cleaned

def extract_headings(file_path: Path) -> set:
    """Extract all heading anchors from a markdown file."""
    if not file_path.exists() or not file_path.is_file():
        return set()
    anchors = set()
    try:
        content = file_path.read_text(encoding='utf-8')
    except Exception:
        return set()
    
    for line in content.splitlines():
        line = line.strip()
        if line.startswith('#'):
            # Count leading #
            heading_text = line.lstrip('#').strip()
            if heading_text:
                slug = slugify_heading(heading_text)
                anchors.add(slug)
                # Also add duplicate variations if needed
    return anchors

def validate_links() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    files_to_check = [repo_root / "README.md"]
    files_to_check.extend(sorted(repo_root.glob("docs/*.md")))

    total_links = 0
    broken_links = []

    for file_path in files_to_check:
        if not file_path.exists():
            continue

        content = file_path.read_text(encoding='utf-8')
        rel_dir = file_path.parent
        file_headings = extract_headings(file_path)

        # Collect all links and images
        all_matches = LINK_PATTERN.findall(content) + IMAGE_PATTERN.findall(content)

        for text, raw_target in all_matches:
            target = raw_target.strip()

            # Ignore absolute/protocol links
            if target.startswith(('http://', 'https://', 'mailto:', 'ftp:', '#!')):
                continue

            # Ignore html tags or javascript pseudo-protocols
            if target.startswith(('javascript:', '<', 'data:')):
                continue

            total_links += 1

            # Split path and anchor
            if '#' in target:
                target_path_str, anchor = target.split('#', 1)
            else:
                target_path_str, anchor = target, ''

            # If anchor only: points within same file
            if not target_path_str:
                if anchor and anchor not in file_headings:
                    broken_links.append({
                        "file": str(file_path.relative_to(repo_root)),
                        "text": text,
                        "target": target,
                        "reason": f"Anchor '#{anchor}' not found in file (available: {len(file_headings)} headings)"
                    })
                continue

            # Path can be relative to current file or repo root
            resolved_from_rel = (rel_dir / target_path_str).resolve()
            resolved_from_root = (repo_root / target_path_str).resolve()

            if resolved_from_rel.exists():
                target_path = resolved_from_rel
            elif resolved_from_root.exists():
                target_path = resolved_from_root
            else:
                broken_links.append({
                    "file": str(file_path.relative_to(repo_root)),
                    "text": text,
                    "target": target,
                    "reason": f"File does not exist (tried: {rel_dir / target_path_str})"
                })
                continue

            # If an anchor is specified on another file
            if anchor and target_path.suffix.lower() == '.md':
                other_headings = extract_headings(target_path)
                if anchor not in other_headings:
                    broken_links.append({
                        "file": str(file_path.relative_to(repo_root)),
                        "text": text,
                        "target": target,
                        "reason": f"Anchor '#{anchor}' not found in target file {target_path_str}"
                    })

    print(f"Validated {total_links} relative links across {len(files_to_check)} documents.")

    if broken_links:
        print(f"\n❌ Found {len(broken_links)} broken relative link(s):")
        for err in broken_links:
            print(f"  - {err['file']}: [{err['text']}]({err['target']})")
            print(f"    Reason: {err['reason']}")
        return 1
    else:
        print("✅ All relative links and anchors are valid!")
        return 0

if __name__ == "__main__":
    sys.exit(validate_links())
