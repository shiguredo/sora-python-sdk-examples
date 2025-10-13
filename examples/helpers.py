import json
import os
import platform
from typing import Any, Callable
from uuid import uuid4

from sora_sdk import (
    SoraVideoCodecImplementation,
    SoraVideoCodecPreference,
    get_video_codec_capability,
)

__all__ = [
    "coerce_bool",
    "coerce_int",
    "coerce_json",
    "coerce_list",
    "get_config_value",
    "get_video_codec_preference",
    "resolve_channel_id",
]


def coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, "", 0):
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    value_str = str(value).strip().lower()
    if value_str in {"1", "true", "yes", "on"}:
        return True
    if value_str in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"ブール値として解釈できない値です: {value!r}")


def coerce_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, int):
        return value
    return int(value)


def coerce_json(value: Any) -> dict[str, Any] | list[Any] | None:
    if value in (None, ""):
        return None
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def coerce_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value]
    return [item.strip() for item in str(value).split(",") if item.strip()]


_TYPE_CASTERS: dict[type[Any], Callable[[Any], Any]] = {
    bool: coerce_bool,
    int: lambda v: int(v),
    float: lambda v: float(v),
    str: lambda v: str(v),
}

_NAME_CASTERS: dict[str, Callable[[Any], Any]] = {
    "bool": coerce_bool,
    "boolean": coerce_bool,
    "int": lambda v: int(v),
    "integer": lambda v: int(v),
    "float": lambda v: float(v),
    "json": lambda v: _ensure_json(v),
    "dict": lambda v: _ensure_json(v),
    "mapping": lambda v: _ensure_json(v),
    "list": coerce_list,
    "tuple": lambda v: tuple(coerce_list(v)),
    "set": lambda v: set(coerce_list(v)),
    "str": lambda v: str(v),
    "string": lambda v: str(v),
    "auto": None,  # 特別扱い
}


def get_config_value(
    env_name: str,
    cli_value: Any | None,
    *,
    default: Any | None = None,
    required: bool = False,
    type_: str | type[Any] | Callable[[Any], Any] | None = "auto",
    cast: str | type[Any] | Callable[[Any], Any] | None = None,
    **kwargs: Any,
) -> Any | None:
    """環境変数・CLI 引数・既定値の順に設定値を解決し、必要に応じて型変換する。"""

    if "type" in kwargs:
        if type_ not in (None, "auto"):
            raise TypeError("`type` と `type_` を同時に指定できません")
        type_ = kwargs.pop("type")
    if kwargs:
        unexpected = ", ".join(kwargs.keys())
        raise TypeError(f"未対応のキーワード引数です: {unexpected}")

    env_value = os.getenv(env_name)
    source_value: Any | None = None

    if env_value not in (None, ""):
        source_value = env_value
    elif cli_value is not None:
        source_value = cli_value

    if source_value is None:
        if default is not None:
            return default
        if required:
            raise ValueError(f"環境変数 {env_name} が設定されていません")
        return None

    # 後方互換のため cast を優先的に解釈する
    type_hint = cast if cast is not None and type_ in (None, "auto") else type_
    caster = _resolve_caster(type_hint, default)
    return caster(source_value)


def _resolve_caster(
    type_hint: str | type[Any] | Callable[[Any], Any] | None,
    default: Any | None,
) -> Callable[[Any], Any]:
    if callable(type_hint) and not isinstance(type_hint, type):
        return type_hint

    if isinstance(type_hint, type):
        if type_hint in _TYPE_CASTERS:
            return _TYPE_CASTERS[type_hint]
        if issubclass(type_hint, dict):
            return _ensure_json
        if issubclass(type_hint, list):
            return coerce_list
        if issubclass(type_hint, tuple):
            return lambda v: tuple(coerce_list(v))
        if issubclass(type_hint, set):
            return lambda v: set(coerce_list(v))
        return lambda v: type_hint(v)

    if isinstance(type_hint, str) and type_hint:
        key = type_hint.lower()
        if key in ("auto", "default"):
            return lambda v: _auto_cast(v, default)
        if key in _NAME_CASTERS and _NAME_CASTERS[key] is not None:
            return _NAME_CASTERS[key]
        raise ValueError(f"未対応の型指定です: {type_hint}")

    return lambda v: _auto_cast(v, default)


def _auto_cast(value: Any, default: Any | None) -> Any:
    """
    default の型をもとに簡易的にキャストする。

    bool/int/float は専用パーサ、dict/list は JSON 文字列として扱う。
    default が None の場合は文字列のまま返す。
    """

    if default is None or value is None:
        return value

    default_type = type(default)

    if default_type in _TYPE_CASTERS:
        return _TYPE_CASTERS[default_type](value)

    if isinstance(default, dict):
        return _ensure_json(value)

    if isinstance(default, list):
        return coerce_list(value)

    if isinstance(default, tuple):
        return tuple(coerce_list(value))

    if isinstance(default, set):
        return set(coerce_list(value))

    return value


def _ensure_json(value: Any) -> dict[str, Any] | list[Any]:
    parsed = coerce_json(value)
    if parsed is None:
        raise ValueError(f"JSON として解釈できない値です: {value!r}")
    return parsed


def get_video_codec_preference(openh264_path: str | None) -> SoraVideoCodecPreference:
    capabilities = get_video_codec_capability(openh264=openh264_path)

    codecs = []
    for engine in capabilities.engines:
        # Darwin では OpenH264 を採用しない
        if (
            platform.system() == "Darwin"
            and engine.name == SoraVideoCodecImplementation.CISCO_OPENH264
        ):
            continue

        for codec in engine.codecs:
            # codec が encoder と decoder が true の場合のみ追加する
            if codec.encoder and codec.decoder:
                codecs.append(
                    SoraVideoCodecPreference.Codec(
                        type=codec.type,
                        decoder=engine.name,
                        encoder=engine.name,
                    )
                )

    return SoraVideoCodecPreference(codecs=codecs)


def resolve_channel_id(
    channel_id: str | None,
    channel_id_prefix: str | None,
) -> str:
    """
    チャンネル ID を決定する。

    明示的なチャンネル ID が与えられていればそれを返し、そうでなければ
    プレフィックスに UUID4 を連結して生成する。
    """

    if channel_id not in (None, ""):
        return str(channel_id)

    if channel_id_prefix not in (None, ""):
        return f"{channel_id_prefix}{uuid4()}"

    raise ValueError("チャンネル ID かプレフィックスを指定してください")
