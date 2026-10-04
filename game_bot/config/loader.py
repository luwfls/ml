from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:
    yaml = None

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
RUNTIME_DIRS = (
    PROJECT_ROOT / "runtime",
    PROJECT_ROOT / "runtime" / "screenshots",
    PROJECT_ROOT / "runtime" / "debug",
    PROJECT_ROOT / "runtime" / "logs",
    PROJECT_ROOT / "runtime" / "replays",
)


def ensure_runtime_dirs() -> list[Path]:
    for path in RUNTIME_DIRS:
        path.mkdir(parents=True, exist_ok=True)
    return list(RUNTIME_DIRS)


def load_settings(path: str | Path | None = None) -> dict:
    config_path = Path(path) if path is not None else CONFIG_DIR / "settings.yaml"
    return load_yaml_config(config_path)


def load_regions(path: str | Path | None = None) -> dict:
    return load_yaml_config(Path(path) if path is not None else CONFIG_DIR / "regions.yaml").get("regions", {})


def load_targets(path: str | Path | None = None) -> dict:
    return load_yaml_config(Path(path) if path is not None else CONFIG_DIR / "targets.yaml").get("targets", {})


def load_popups(path: str | Path | None = None) -> dict:
    return load_yaml_config(Path(path) if path is not None else CONFIG_DIR / "popups.yaml").get("popups", {})


def load_actions(path: str | Path | None = None) -> dict:
    return load_yaml_config(Path(path) if path is not None else CONFIG_DIR / "actions.yaml").get("actions", {})


def load_states(path: str | Path | None = None) -> dict:
    return load_yaml_config(Path(path) if path is not None else CONFIG_DIR / "states.yaml").get("states", {})


def load_policy(path: str | Path | None = None) -> dict:
    data = load_yaml_config(Path(path) if path is not None else CONFIG_DIR / "policy.yaml")
    if "policy" in data:
        return data.get("policy") or {}
    policies = data.get("policies")
    if isinstance(policies, dict):
        return policies
    return {}


def load_yaml_config(path: str | Path) -> dict:
    config_path = Path(path)
    if not config_path.exists():
        return {}
    return parse_yaml_text(config_path, config_path.read_text(encoding="utf-8"))


def parse_yaml_text(path: str | Path, text: str) -> dict:
    config_path = Path(path)
    if yaml is None:
        data = _load_simple_yaml_text(config_path, text)
    else:
        data = yaml.safe_load(text)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a mapping: {config_path}")
    return data


def _load_simple_yaml_text(path: Path, text: str) -> dict:
    data: dict = {}
    stack: list[tuple[int, dict]] = [(-1, data)]

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip(" "))
        key, separator, value = line.strip().partition(":")
        if not separator:
            raise ValueError(f"Install PyYAML to parse config line in {path}: {raw_line}")

        while stack and indent <= stack[-1][0]:
            stack.pop()

        parent = stack[-1][1]
        parsed_value = _parse_scalar(value.strip())
        parent[key] = parsed_value

        if parsed_value == {}:
            stack.append((indent, parsed_value))

    return data


def _parse_scalar(value: str):
    if value == "":
        return {}
    if value in {"{}", "[]"}:
        return {} if value == "{}" else []
    if value in {"true", "false"}:
        return value == "true"
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value
