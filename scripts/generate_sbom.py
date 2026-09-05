from __future__ import annotations

import importlib.metadata
import json
import platform
import re
import hashlib
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from packaging.requirements import Requirement


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs" / "sbom.cdx.json"


def normalized_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def main() -> None:
    requirements_path = ROOT / "requirements.txt"
    requirement_lines = [
        line.strip() for line in requirements_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    direct_requirements = [Requirement(line) for line in requirement_lines]
    direct_names = {normalized_name(requirement.name) for requirement in direct_requirements}
    installed = {
        normalized_name(distribution.metadata["Name"]): distribution
        for distribution in importlib.metadata.distributions()
    }
    missing = sorted(direct_names - installed.keys())
    if missing:
        raise SystemExit("Runtime requirements are not installed: " + ", ".join(missing))

    selected_extras = {normalized_name(item.name): set(item.extras) for item in direct_requirements}
    queue = deque(sorted(direct_names))
    reachable = set()
    dependency_names = {}
    while queue:
        normalized = queue.popleft()
        if normalized in reachable:
            continue
        reachable.add(normalized)
        distribution = installed[normalized]
        children = set()
        extras = selected_extras.get(normalized, set())
        for raw_requirement in distribution.requires or []:
            requirement = Requirement(raw_requirement)
            environments = [{"extra": ""}] + [{"extra": extra} for extra in extras]
            if requirement.marker and not any(requirement.marker.evaluate(env) for env in environments):
                continue
            child = normalized_name(requirement.name)
            if child not in installed:
                raise SystemExit(f"Dependency {requirement.name} required by {distribution.metadata['Name']} is not installed.")
            selected_extras.setdefault(child, set()).update(requirement.extras)
            children.add(child)
            queue.append(child)
        dependency_names[normalized] = children

    components = []
    refs = {}
    for normalized in sorted(reachable):
        distribution = installed[normalized]
        name = distribution.metadata["Name"]
        ref = f"pkg:pypi/{normalized}@{distribution.version}"
        refs[normalized] = ref
        component = {
            "type": "library", "name": name, "version": distribution.version,
            "bom-ref": ref, "purl": ref,
            "scope": "required",
            "properties": [{"name": "aurafoods.direct-requirement", "value": str(normalized_name(name) in direct_names).lower()}],
        }
        components.append(component)
    dependencies = [
        {"ref": refs[name], "dependsOn": sorted(refs[child] for child in dependency_names.get(name, set()))}
        for name in sorted(reachable)
    ]
    project_apps = [name for name in ("erp", "frontend", "shop", "sales", "crm") if (ROOT / name).is_dir()]
    static_assets = [path.relative_to(ROOT).as_posix() for path in sorted((ROOT / "static").rglob("*")) if path.is_file()]
    document = {
        "bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tools": [{"vendor": "Aura Foods", "name": "generate_sbom.py", "version": "1"}],
            "component": {"type": "application", "name": "aurafoods-unified", "version": "6.7-unified"},
            "properties": [
                {"name": "python.version", "value": platform.python_version()},
                {"name": "project.apps", "value": ",".join(project_apps)},
                {"name": "static.asset.count", "value": str(len(static_assets))},
                {"name": "requirements.sha256", "value": hashlib.sha256(requirements_path.read_bytes()).hexdigest()},
                {"name": "requirements.direct.count", "value": str(len(direct_names))},
            ],
        },
        "components": components,
        "dependencies": dependencies,
        "properties": [{"name": "aurafoods.static.assets", "value": json.dumps(static_assets)}],
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(document, indent=2), encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
