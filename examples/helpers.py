import argparse
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from sora_sdk import (
    SoraVideoCodecImplementation,
    SoraVideoCodecPreference,
    get_video_codec_capability,
)


# .env ファイルを読み込んで環境変数に設定する
# 既存の環境変数は上書きしない
def _load_env_file(env_file: str | Path, encoding: str = "utf-8") -> None:
    env_path = Path(env_file)
    if not env_path.exists():
        return

    with open(env_path, encoding=encoding) as f:
        for line in f:
            line = line.strip()
            # 空行とコメントをスキップ
            if not line or line.startswith("#"):
                continue

            # KEY=VALUE 形式を解析
            if "=" not in line:
                continue

            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()

            # 引用符を除去（先頭と末尾が同じ引用符の場合）
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]

            # 既存の環境変数は上書きしない
            os.environ.setdefault(key, value)


# 文字列が真偽値として真かどうかを判定する
def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


# 文字列をカンマまたは空白で分割してリストにする
# カンマ区切りと空白区切りを自動判定する
def _split_list(raw: str) -> list[str]:
    stripped = raw.strip()
    if not stripped:
        return []
    # カンマのみで区切られているケース（空白を含まない）
    if "," in stripped and " " not in stripped.replace(",", ""):
        return [item for item in (part.strip() for part in stripped.split(",")) if item]
    # それ以外は空白区切りとして扱う
    return [item for item in stripped.split() if item]


# 環境変数に基づいて未指定のオプションを補完する ArgumentParser
# env_prefix="SORA_" の場合、--channel-id-prefix は SORA_CHANNEL_ID_PREFIX 環境変数を参照する
# CLI で指定された値が優先される
# env_file を指定すると、初期化時にその .env ファイルを読み込む
class EnvPrefixArgumentParser(argparse.ArgumentParser):
    def __init__(
        self,
        *args,
        env_prefix: str = "",
        env_file: str | Path = ".env",
        env_file_encoding: str = "utf-8",
        **kwargs,
    ) -> None:
        self._env_prefix = env_prefix or ""
        self._dest_to_opts: dict[str, list[str]] = {}

        # .env ファイルを読み込む
        if env_file:
            _load_env_file(env_file, encoding=env_file_encoding)

        super().__init__(*args, **kwargs)

    # 引数を追加してオプション文字列を記録する
    def add_argument(self, *args, **kwargs):
        action = super().add_argument(*args, **kwargs)
        option_strings = getattr(action, "option_strings", None)
        if option_strings:
            self._dest_to_opts[action.dest] = list(option_strings)
        return action

    # 環境変数から引数リストを構築する
    # CLI で既に指定されている引数は環境変数から補完しない
    def _build_env_args(self, args: list[str]) -> list[str]:
        seen_options = {token for token in args if isinstance(token, str) and token.startswith("-")}

        injected: list[str] = []
        for action in self._actions:
            option_strings = getattr(action, "option_strings", None)
            if not option_strings:
                continue

            env_name = self._build_env_name(action.dest)
            if not env_name or env_name not in os.environ:
                continue

            # 既に CLI で指定されている場合はスキップ
            if any(opt in seen_options for opt in option_strings):
                continue

            raw = os.environ[env_name]

            # store_true アクションの場合
            if isinstance(action, argparse._StoreTrueAction):
                if _truthy(raw):
                    injected.append(option_strings[0])
                continue
            # store_false アクションの場合
            if isinstance(action, argparse._StoreFalseAction):
                if not _truthy(raw):
                    injected.append(option_strings[0])
                continue
            # store_const アクションの場合
            if isinstance(action, argparse._StoreConstAction):
                if _truthy(raw):
                    injected.append(option_strings[0])
                continue

            # 引数の数に応じて処理を分岐
            if action.nargs in (None, 1):
                injected.extend([option_strings[0], raw])
            elif action.nargs in ("+", "*"):
                parts = _split_list(raw)
                if parts or action.nargs == "+":
                    injected.extend([option_strings[0], *parts])
            elif isinstance(action.nargs, int):
                parts = _split_list(raw)
                if len(parts) != action.nargs:
                    raise ValueError(
                        f"{env_name} expects {action.nargs} values, got {len(parts)}: {raw!r}"
                    )
                injected.extend([option_strings[0], *parts])
            else:
                injected.extend([option_strings[0], raw])

        return injected

    # dest から環境変数名を構築する
    # 例: env_prefix="SORA_", dest="channel_id" -> "SORA_CHANNEL_ID"
    def _build_env_name(self, dest: str | None) -> str | None:
        if not dest:
            return None
        if not self._env_prefix:
            return None
        return f"{self._env_prefix}{dest.upper().replace('-', '_')}"

    # 引数をパースする
    # 環境変数から補完した引数を先頭に、CLI 引数を後に配置することで CLI 側を優先させる
    def parse_args(self, args: list[str] | None = None, namespace=None):
        if args is None:
            args = sys.argv[1:]
        env_args = self._build_env_args(list(args))
        # env_args を先頭にして CLI 側を優先させる（後勝ち）
        return super().parse_args(env_args + list(args), namespace=namespace)


# argparse のカスタム型として JSON オブジェクトをパースする
def json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"JSON を解析できません: {exc}") from exc
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("JSON オブジェクト（{}）を指定してください")
    return parsed


# ビデオコーデックの優先順位を取得する
# エンコーダーとデコーダーの両方が利用可能なコーデックのみを含める
# macOS では OpenH264 を除外する
def get_video_codec_preference(openh264_path: str | None) -> SoraVideoCodecPreference:
    capabilities = get_video_codec_capability(openh264=openh264_path)

    codecs = []
    for engine in capabilities.engines:
        # macOS では OpenH264 を除外する
        if (
            platform.system() == "Darwin"
            and engine.name == SoraVideoCodecImplementation.CISCO_OPENH264
        ):
            continue

        for codec in engine.codecs:
            # エンコーダーとデコーダーの両方が利用可能な場合のみ追加
            if codec.encoder and codec.decoder:
                codecs.append(
                    SoraVideoCodecPreference.Codec(
                        type=codec.type,
                        decoder=engine.name,
                        encoder=engine.name,
                    )
                )

    return SoraVideoCodecPreference(codecs=codecs)


# チャンネル ID を解決する
# channel_id が指定されていればそれを使用し、なければ channel_id_prefix と UUID から生成する
def resolve_channel_id(
    channel_id: str | None,
    channel_id_prefix: str | None,
) -> str:
    if channel_id not in (None, ""):
        return str(channel_id)

    if channel_id_prefix not in (None, ""):
        return f"{channel_id_prefix}{uuid4()}"

    raise ValueError("チャンネル ID かプレフィックスを指定してください")
