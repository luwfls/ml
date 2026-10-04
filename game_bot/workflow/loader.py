from pathlib import Path
from typing import Any

from game_bot.config.loader import PROJECT_ROOT, parse_yaml_text
from game_bot.workflow.models import WorkflowDefinition, WorkflowNodeDefinition, WorkflowTransition

WORKFLOWS_DIR = PROJECT_ROOT / "workflows"
_RESERVED_NODE_FIELDS = {
    "id",
    "type",
    "name",
    "next",
    "on_fail",
    "timeout_ms",
    "retries",
    "description",
    "transitions",
}


class WorkflowValidationError(ValueError):
    pass


def load_workflow(path: str | Path) -> WorkflowDefinition:
    workflow_path = Path(path)
    if not workflow_path.is_absolute():
        workflow_path = PROJECT_ROOT / workflow_path
    if not workflow_path.exists():
        raise WorkflowValidationError(f"Workflow file does not exist: {workflow_path}")
    data = parse_yaml_text(workflow_path, workflow_path.read_text(encoding="utf-8"))
    return parse_workflow(data, source=workflow_path)


def parse_workflow(data: dict[str, Any], *, source: str | Path = "<workflow>") -> WorkflowDefinition:
    source_path = Path(source)
    workflow_id = _required_str(data, "id", source_path)
    start = _required_str(data, "start", source_path)
    name = _optional_str(data.get("name"), "name", source_path) or workflow_id
    max_steps = _optional_int(data.get("max_steps"), "max_steps", source_path, default=100)
    max_failures = _optional_int(data.get("max_failures"), "max_failures", source_path, default=3)
    nodes = _parse_nodes(data.get("nodes"), source_path)

    workflow = WorkflowDefinition(
        id=workflow_id,
        name=name,
        start=start,
        max_steps=max_steps,
        max_failures=max_failures,
        nodes=nodes,
    )
    validate_workflow(workflow, source=source_path)
    return workflow


def validate_workflow(workflow: WorkflowDefinition, *, source: str | Path = "<workflow>") -> None:
    source_path = Path(source)
    if workflow.start not in workflow.nodes:
        raise WorkflowValidationError(f"Workflow start node does not exist in {source_path}: {workflow.start}")

    for node in workflow.nodes.values():
        for field_name, target in (("next", node.next), ("on_fail", node.on_fail)):
            if target is not None and target not in workflow.nodes:
                raise WorkflowValidationError(
                    f"Node {node.id}.{field_name} references missing node in {source_path}: {target}"
                )
        for transition in node.transitions:
            if transition.to not in workflow.nodes:
                raise WorkflowValidationError(
                    f"Node {node.id}.transitions references missing node in {source_path}: {transition.to}"
                )


def _parse_nodes(value: Any, source: Path) -> dict[str, WorkflowNodeDefinition]:
    if not isinstance(value, dict) or not value:
        raise WorkflowValidationError(f"Workflow nodes must be a non-empty mapping: {source}")

    nodes: dict[str, WorkflowNodeDefinition] = {}
    for node_id, node_data in value.items():
        if not isinstance(node_id, str) or not node_id.strip():
            raise WorkflowValidationError(f"Workflow node id must be a non-empty string: {source}")
        if not isinstance(node_data, dict):
            raise WorkflowValidationError(f"Workflow node must be a mapping in {source}: {node_id}")
        node = _parse_node(node_id.strip(), node_data, source)
        nodes[node.id] = node
    return nodes


def _parse_node(node_id: str, data: dict[str, Any], source: Path) -> WorkflowNodeDefinition:
    node_type = _required_str(data, "type", source, prefix=f"Node {node_id}")
    transitions = _parse_transitions(data.get("transitions"), node_id, source)
    params = {key: value for key, value in data.items() if key not in _RESERVED_NODE_FIELDS}
    declared_id = data.get("id")
    if declared_id is not None and declared_id != node_id:
        raise WorkflowValidationError(f"Node {node_id}.id must match its mapping key in {source}: {declared_id}")

    return WorkflowNodeDefinition(
        id=node_id,
        type=node_type,
        name=_optional_str(data.get("name"), f"{node_id}.name", source),
        next=_optional_str(data.get("next"), f"{node_id}.next", source),
        on_fail=_optional_str(data.get("on_fail"), f"{node_id}.on_fail", source),
        timeout_ms=_optional_int(data.get("timeout_ms"), f"{node_id}.timeout_ms", source),
        retries=_optional_int(data.get("retries"), f"{node_id}.retries", source, default=0),
        description=_optional_str(data.get("description"), f"{node_id}.description", source),
        transitions=transitions,
        params=params,
    )


def _parse_transitions(value: Any, node_id: str, source: Path) -> tuple[WorkflowTransition, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise WorkflowValidationError(f"Node {node_id}.transitions must be a list: {source}")

    transitions = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise WorkflowValidationError(f"Node {node_id}.transitions[{index}] must be a mapping: {source}")
        when = _required_str(item, "when", source, prefix=f"Node {node_id}.transitions[{index}]")
        to = _required_str(item, "to", source, prefix=f"Node {node_id}.transitions[{index}]")
        transitions.append(WorkflowTransition(when=when, to=to))
    return tuple(transitions)


def _required_str(data: dict[str, Any], key: str, source: Path, *, prefix: str = "Workflow") -> str:
    value = data.get(key)
    text = _optional_str(value, key, source)
    if text is None:
        raise WorkflowValidationError(f"{prefix}.{key} is required in {source}")
    return text


def _optional_str(value: Any, field_name: str, source: Path) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise WorkflowValidationError(f"{field_name} must be a non-empty string in {source}")
    return value.strip()


def _optional_int(value: Any, field_name: str, source: Path, *, default: int | None = None) -> int | None:
    if value is None:
        return default
    if not isinstance(value, int) or value < 0:
        raise WorkflowValidationError(f"{field_name} must be a non-negative integer in {source}")
    return value
