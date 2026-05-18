import pathlib
import json
import hashlib

md_files = [
    "docs/acp-setup.md",
    "docs/audits/api-concurrency-worker-readiness-audit.md",
    "docs/audits/telemetry-panopticon-audit.md",
    "docs/audits/test-suite-reality-pressure-audit.md",
    "docs/governance/release-gate-findings-lifecycle.md",
    "docs/governance/serialized-digestion-pipeline.md",
    "docs/governance/telemetry-consent-enforcement.md",
    "docs/install.md",
    "docs/protocol-surfaces.md",
    "docs/proxy-setup.md",
    "docs/rig-mcp-capability-map.md"
]

doc_types = {
    "api-concurrency-worker-readiness-audit": "audit",
    "telemetry-panopticon-audit": "audit",
    "test-suite-reality-pressure-audit": "audit",
    "release-gate-findings-lifecycle": "governance",
    "serialized-digestion-pipeline": "governance",
    "telemetry-consent-enforcement": "governance",
    "acp-setup": "guide",
    "install": "guide",
    "protocol-surfaces": "reference",
    "proxy-setup": "guide",
    "rig-mcp-capability-map": "reference"
}

def get_sha256(text):
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()

def parse_markdown(text):
    lines = text.splitlines()
    blocks = []
    i = 0
    block_counter = 1

    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        
        if line.startswith('```'):
            lang = line[3:].strip()
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1
            content = '\n'.join(code_lines)
            if lang == 'mermaid':
                blocks.append({
                    "block_id": f"mermaid-{block_counter}",
                    "type": "mermaid",
                    "content": content,
                    "disclosure": {"level": "standard", "initially_visible": True}
                })
            elif lang == 'json':
                blocks.append({
                    "block_id": f"json-{block_counter}",
                    "type": "json",
                    "content": content,
                    "disclosure": {"level": "standard", "initially_visible": True}
                })
            else:
                blocks.append({
                    "block_id": f"code-{block_counter}",
                    "type": "code",
                    "language": lang if lang else "text",
                    "content": content,
                    "disclosure": {"level": "standard", "initially_visible": True}
                })
            block_counter += 1
            continue

        if line.startswith('#'):
            level = len(line) - len(line.lstrip('#'))
            title = line.lstrip('#').strip()
            blocks.append({
                "block_id": f"h{level}-{block_counter}",
                "type": "heading",
                "level": min(level, 6),
                "content": title,
                "disclosure": {"level": "standard", "initially_visible": True}
            })
            block_counter += 1
            i += 1
            continue

        if line.startswith('|'):
            cols = [c.strip() for c in line.split('|')[1:-1]]
            i += 1
            if i < len(lines) and lines[i].strip().startswith('|') and '-' in lines[i]:
                i += 1
            rows = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                row = [c.strip() for c in lines[i].split('|')[1:-1]]
                rows.append(row)
                i += 1
            blocks.append({
                "block_id": f"table-{block_counter}",
                "type": "table",
                "columns": cols,
                "rows": rows,
                "disclosure": {"level": "standard", "initially_visible": True}
            })
            block_counter += 1
            continue

        if line.startswith('- ') or line.startswith('* ') or (line[0].isdigit() and '. ' in line[:5]):
            items = []
            ordered = line[0].isdigit()
            while i < len(lines):
                cur = lines[i].strip()
                if cur.startswith('- ') or cur.startswith('* '):
                    items.append(cur[2:].strip())
                    i += 1
                elif cur and cur[0].isdigit() and '. ' in cur[:5]:
                    parts = cur.split('. ', 1)
                    items.append(parts[1].strip() if len(parts) > 1 else "")
                    i += 1
                else:
                    if not cur or cur.startswith('#') or cur.startswith('|') or cur.startswith('```'):
                        break
                    if items:
                        items[-1] += " " + cur
                    i += 1
            blocks.append({
                "block_id": f"list-{block_counter}",
                "type": "list",
                "ordered": ordered,
                "items": items,
                "disclosure": {"level": "standard", "initially_visible": True}
            })
            block_counter += 1
            continue

        p_lines = []
        while i < len(lines):
            cur = lines[i].strip()
            if not cur or cur.startswith('#') or cur.startswith('|') or cur.startswith('```') or cur.startswith('- ') or cur.startswith('* ') or (cur[0].isdigit() and '. ' in cur[:5]):
                break
            p_lines.append(cur)
            i += 1
        content = ' '.join(p_lines)
        blocks.append({
            "block_id": f"p-{block_counter}",
            "type": "paragraph",
            "content": content,
            "disclosure": {"level": "standard", "initially_visible": True}
        })
        block_counter += 1

    return blocks

manifest_path = pathlib.Path("docs/json/documentation_migration_manifest.v1.json")
manifest_data = json.loads(manifest_path.read_text())

migrations_added = 0

for md_path_str in md_files:
    md_path = pathlib.Path(md_path_str)
    if not md_path.exists():
        print(f"Skipping {md_path_str}, does not exist.")
        continue

    text = md_path.read_text()
    sha_old = get_sha256(text)

    stem = md_path.stem
    doc_type = doc_types.get(stem, "other")

    if "audits" in md_path.parts:
        new_path_str = f"docs/json/audits/{stem}.v1.json"
    elif "governance" in md_path.parts:
        new_path_str = f"docs/json/governance/{stem}.v1.json"
    else:
        new_path_str = f"docs/json/{stem}.v1.json"

    new_path = pathlib.Path(new_path_str)
    new_path.parent.mkdir(parents=True, exist_ok=True)

    blocks = parse_markdown(text)

    title = stem.replace("-", " ").title()
    for b in blocks:
        if b["type"] == "heading":
            title = b["content"]
            break

    summary = f"Canonical JSON migration for {stem}."
    for b in blocks:
        if b["type"] == "paragraph":
            summary = b["content"][:200]
            if len(b["content"]) > 200:
                summary += "..."
            break

    json_obj = {
        "schema_version": "rig.documentation.page.v1",
        "document_id": stem,
        "document_type": doc_type,
        "title": title,
        "summary": summary,
        "status": "active",
        "created_at": "2026-05-18",
        "updated_at": "2026-05-18",
        "source_commit": "c92a220a",
        "owners": ["maintainer"],
        "tags": [doc_type, "migration"],
        "audience": ["contributor", "maintainer"],
        "canonical_path": new_path_str,
        "render": {
            "toc": True,
            "search_index": True
        },
        "sections": blocks,
        "provenance": {
            "source_files": [md_path_str]
        }
    }

    json_text = json.dumps(json_obj, indent=2) + "\n"
    new_path.write_text(json_text)
    sha_new = get_sha256(json_text)

    # Check if migration already in manifest
    existing = False
    for m in manifest_data["migrations"]:
        if m["old_path"] == md_path_str:
            m["status"] = "deleted"
            m["content_sha256_new"] = sha_new
            m["review_notes"] = "Markdown file deleted after migration to canonical JSON format."
            existing = True
            break

    if not existing:
        manifest_data["migrations"].append({
            "old_path": md_path_str,
            "new_path": new_path_str,
            "status": "deleted",
            "reason": f"Porting {stem} to canonical JSON format and deleting old Markdown.",
            "content_sha256_old": sha_old,
            "content_sha256_new": sha_new,
            "references_updated": True,
            "review_notes": "Markdown file deleted after migration to canonical JSON format."
        })

    # Delete old markdown file
    md_path.unlink()
    print(f"Migrated {md_path_str} -> {new_path_str} and deleted MD.")
    migrations_added += 1

manifest_path.write_text(json.dumps(manifest_data, indent=2) + "\n")
print(f"Updated manifest with {migrations_added} migrations.")
