import platform
from typing import Optional

from sora_sdk import (
    SoraVideoCodecImplementation,
    SoraVideoCodecPreference,
    get_video_codec_capability,
)


def get_video_codec_preference(openh264_path: Optional[str]) -> SoraVideoCodecPreference:
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
