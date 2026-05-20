from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from rig_relay.compiler.schema_to_code.reader import ModelSpec

DEFAULT_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
DEFAULT_TEMPLATE_NAME = "pydantic_model.py.j2"


def render_template(
    model_spec: ModelSpec | dict, template_path: Path | None = None
) -> str:
    if template_path is not None:
        env = Environment(loader=FileSystemLoader(str(template_path.parent)))
        template = env.get_template(template_path.name)
    else:
        env = Environment(loader=FileSystemLoader(str(DEFAULT_TEMPLATE_DIR)))
        template = env.get_template(DEFAULT_TEMPLATE_NAME)

    if isinstance(model_spec, ModelSpec):
        spec_dict = _model_spec_to_template_dict(model_spec)
    else:
        spec_dict = model_spec

    return template.render(
        contract_family_id=spec_dict["contract_family_id"],
        schema_id=spec_dict["schema_version"],
        imports=spec_dict.get("imports", ["from pydantic import BaseModel"]),
        models=spec_dict.get("models", []),
    )


def write_generated_code(code: str, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(code, encoding="utf-8")
    return output_path


def _model_spec_to_template_dict(spec: ModelSpec) -> dict:
    return {
        "contract_family_id": spec.contract_family_id,
        "schema_version": spec.schema_version,
        "imports": spec.imports,
        "models": spec.models,
    }
