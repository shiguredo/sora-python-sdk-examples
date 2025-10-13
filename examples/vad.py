import json
from threading import Event
from typing import Any

from sora_sdk import (
    Sora,
    SoraAudioFrame,
    SoraAudioStreamSink,
    SoraMediaTrack,
    SoraVAD,
)

from helpers import EnvPrefixArgumentParser, json_object, resolve_channel_id


class VAD:
    def __init__(self, signaling_urls: list[str], channel_id: str, metadata: dict[str, Any] | None):
        # 接続設定
        self._signaling_urls: list[str] = signaling_urls
        self._channel_id: str = channel_id

        # VAD インスタンス
        self._vad = SoraVAD()

        # Sora から払い出される接続 ID
        self._connection_id: str

        # 接続状態管理用のイベント
        self._connected: Event = Event()
        self._closed = Event()

        # 音声出力設定
        self._audio_output_frequency: int = 24000
        self._audio_output_channels: int = 1

        # Sora インスタンスと接続の作成
        self._sora = Sora()

        self._connection = self._sora.create_connection(
            signaling_urls=signaling_urls,
            role="recvonly",
            channel_id=channel_id,
            metadata=metadata,
            audio=True,
            video=False,
        )

        # コールバック関数の設定
        self._connection.on_set_offer = self._on_set_offer
        self._connection.on_notify = self._on_notify
        self._connection.on_disconnect = self._on_disconnect

        self._connection.on_track = self._on_track

    def connect(self):
        self._connection.connect()

        # _connected が set されるまで 30 秒待つ
        assert self._connected.wait(30)

        return self

    def disconnect(self):
        self._connection.disconnect()

    def get_stats(self):
        raw_stats = self._connection.get_stats()
        stats = json.loads(raw_stats)
        return stats

    def _on_set_offer(self, raw_offer):
        offer = json.loads(raw_offer)
        if offer["type"] == "offer":
            self._connection_id = offer["connection_id"]
            print(f"Received 'Offer': connection_id={self._connection_id}")

    def _on_notify(self, raw_message):
        message = json.loads(raw_message)
        # connection.created イベントで接続完了を検知
        if (
            message["type"] == "notify"
            and message["event_type"] == "connection.created"
            and message["connection_id"] == self._connection_id
        ):
            print(
                f"Connected Sora: channel_id={self._channel_id}, connection_id={self._connection_id}"
            )
            self._connected.set()

    def _on_disconnect(self, error_code, message):
        print(f"Disconnected Sora: error_code='{error_code}' message='{message}'")
        self._closed = True
        self._connected.clear()

    def _on_frame(self, frame: SoraAudioFrame):
        # frame が音声である確率を求める
        voice_probability = self._vad.analyze(frame)
        # libwebrtc の判定値 0.95 を超えた場合に音声と判定
        if voice_probability > 0.95:
            print(f"Voice! voice_probability={voice_probability}")
        else:
            pass

    def _on_track(self, track: SoraMediaTrack):
        if track.kind == "audio":
            # 音声トラックを受信するための AudioStreamSink を作成
            self._audio_stream_sink = SoraAudioStreamSink(
                track, self._audio_output_frequency, self._audio_output_channels
            )
            self._audio_stream_sink.on_frame = self._on_frame

    def run(self) -> None:
        self.connect()
        try:
            # 接続が維持されている間はループを継続
            while self._connected.is_set():
                pass
        except KeyboardInterrupt:
            pass
        finally:
            self.disconnect()


def _parse_args(argv: list[str] | None = None):
    parser = EnvPrefixArgumentParser(
        env_prefix="SORA_",
        description="Sora audio stream VAD (Voice Activity Detection) recvonly sample application",
    )
    parser.add_argument(
        "--signaling-url",
        dest="signaling_urls",
        nargs="+",
        metavar="URL",
        help="Sora signaling URL(s). Multiple URLs can be specified for fallback connections (e.g., --signaling-url wss://example1.com --signaling-url wss://example2.com). At least one URL must be provided.",
    )
    parser.add_argument(
        "--channel-id",
        dest="channel_id",
        help="Channel ID to connect to. This identifier is used to join a specific Sora channel for receiving audio streams.",
    )
    parser.add_argument(
        "--channel-id-prefix",
        dest="channel_id_prefix",
        help="Prefix string used for generating a channel ID. When specified, a unique channel ID will be created by combining this prefix with additional identifiers.",
    )
    parser.add_argument(
        "--metadata",
        dest="metadata",
        type=json_object,
        help="JSON metadata object to send during connection. This metadata will be included in the signaling process and can be used for authentication or custom connection parameters.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    signaling_urls = args.signaling_urls
    if not signaling_urls:
        raise ValueError("Signaling URL is not specified")

    # channel_id または channel_id_prefix からチャンネル ID を解決
    channel_id = resolve_channel_id(args.channel_id, args.channel_id_prefix)

    vad_instance = VAD(
        signaling_urls,
        channel_id,
        metadata=args.metadata,
    )
    vad_instance.run()


if __name__ == "__main__":
    main()
