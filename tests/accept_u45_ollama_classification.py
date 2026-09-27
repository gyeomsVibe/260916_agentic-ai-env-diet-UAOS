from pathlib import Path

root = Path(__file__).resolve().parent.parent
source = root / "docs/research/U45-rule-catalog-input.txt"
output = root / "docs/research/U45-ollama-rule-classification.md"

groups = {}
for raw in source.read_text(encoding="utf-8").splitlines():
    category, value = raw.split("|", 1)
    groups.setdefault(category.upper(), []).append(value)

expected = ["# U45 mechanical rule classification"]
for category in sorted(groups):
    expected.extend(f"{category}|{value}" for value in sorted(groups[category]))
expected.append("COUNTS|" + " ".join(f"{category.lower()}={len(groups[category])}" for category in sorted(groups)))
assert output.read_text(encoding="utf-8").splitlines() == expected
