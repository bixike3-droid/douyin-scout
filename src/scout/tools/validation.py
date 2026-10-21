"""Runtime checks for the JSON Schema vocabulary used by the tool registry."""
import math
import re


def validate(value, schema, path="参数"):
    if not isinstance(schema, dict):
        raise ValueError("工具参数定义无效")
    expected = schema.get("type")
    kinds = {
        "object": isinstance(value, dict), "array": isinstance(value, list),
        "string": isinstance(value, str), "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool), "null": value is None,
    }
    if expected and not any(kinds.get(kind, False) for kind in ([expected] if isinstance(expected, str) else expected)):
        raise ValueError(f"{path} 必须为 {expected}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            raise ValueError(f"{path} 必须为有限数值")
        for key, invalid in (("minimum", lambda n: value < n), ("maximum", lambda n: value > n)):
            if key in schema and invalid(schema[key]):
                raise ValueError(f"{path} 不满足 {key}={schema[key]}")
    if "enum" in schema and not any(value == item and isinstance(value, bool) == isinstance(item, bool) for item in schema["enum"]):
        raise ValueError(f"{path} 只能是 {schema['enum']}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                raise ValueError(f"{path} 缺少 {key}")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                validate(item, properties[key], f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                raise ValueError(f"{path} 包含未知字段 {key}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", math.inf):
            raise ValueError(f"{path} 项数超出范围")
        if "items" in schema:
            for index, item in enumerate(value):
                validate(item, schema["items"], f"{path}[{index}]")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", math.inf):
            raise ValueError(f"{path} 长度超出范围")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            raise ValueError(f"{path} 格式不正确")


def parse_arguments(args, schema):
    import json
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (ValueError, TypeError) as exc:
            raise ValueError("参数不是有效的 JSON 对象") from exc
    if not isinstance(args, dict):
        raise ValueError("参数必须为 JSON 对象")
    validate(args, schema)
    return args
