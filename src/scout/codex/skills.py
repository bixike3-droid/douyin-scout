"""Install only product-owned skills into the isolated account Codex home."""
from pathlib import Path


def install(home):
    source = Path(__file__).resolve().parent.parent / "skills"
    for file in source.glob("*/SKILL.md"):
        destination = home / "skills" / file.parent.name / "SKILL.md"
        destination.parent.mkdir(parents=True, exist_ok=True)
        content = file.read_bytes()
        if not destination.exists() or destination.read_bytes() != content:
            destination.write_bytes(content)


def catalog():
    import yaml
    source = Path(__file__).resolve().parent.parent / "skills"
    entries = []
    for file in sorted(source.glob("*/SKILL.md")):
        text = file.read_text(encoding="utf-8")
        metadata = yaml.safe_load(text.split("---", 2)[1])
        entries.append({"name": metadata["name"], "description": metadata["description"], "content": text})
    return entries
