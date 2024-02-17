import argparse
import json
import os
from threading import Event
from typing import Any, Dict, List

import cv2
import sounddevice
from sora_sdk import AudioSource, Sora, SoraConnection, VideoSource


class SendOnly:
    _sora: Sora
    _connection: SoraConnection

    _connection_id: str

    _connected: Event
    _closed: bool = False

    _audio_source: AudioSource
    _video_source: VideoSource

    _video_capture: cv2.VideoCapture

    def __init__(
        self,
        # python 3.8 まで対応なので list[str] ではなく List[str] にする
        signaling_urls: List[str],
        channel_id: str,
        metadata,
        camera_id,
        audio_codec_type,
        video_codec_type,
        video_bit_rate,
        video_width,
        video_height,
        openh264,
        channels=1,
        samplerate=16000,
    ):
        # FIXME: audio_channels / audio_sample_rate にする
        self.channels = channels
        self.samplerate = samplerate

        self._sora = Sora(openh264=openh264)

        self._audio_source = self._sora.create_audio_source(self.channels, self.samplerate)
        self._video_source = self._sora.create_video_source()

        self._connection = self._sora.create_connection(
            signaling_urls=signaling_urls,
            role="sendonly",
            channel_id=channel_id,
            metadata=metadata,
            audio_codec_type=audio_codec_type,
            video_codec_type=video_codec_type,
            video_bit_rate=video_bit_rate,
            audio_source=self._audio_source,
            video_source=self._video_source,
        )

        self._connection.on_set_offer = self._on_set_offer
        self._connection.on_notify = self._on_notify
        self._connection.on_disconnect = self._on_disconnect

        self._video_capture = cv2.VideoCapture(camera_id)
        if video_width is not None:
            self._video_capture.set(cv2.CAP_PROP_FRAME_WIDTH, video_width)
        if video_height is not None:
            self._video_capture.set(cv2.CAP_PROP_FRAME_HEIGHT, video_height)

    def connect(self):
        self._connection.connect()

        # XXX: マジックナンバーを使っているので修正する
        assert self._connected.wait(timeout=10), "接続がタイムアウトしました"

    def disconnect(self):
        self._connection.disconnect()

    def _on_notify(self, raw_message: str):
        message: Dict[str, Any] = json.loads(raw_message)
        # 自分の connection_id の connection.created が通知されたら接続完了フラグを立てる
        if (
            message["type"] == "notify"
            and message["event_type"] == "connection.created"
            and message["connection_id"] == self._connection_id
        ):
            self._connected.set()

    def _on_set_offer(self, raw_message: str):
        message: Dict[str, Any] = json.loads(raw_message)
        # 自分の connection_id を保存する
        if message["type"] == "offer":
            self._connection_id = message["connection_id"]

    def _on_disconnect(self, error_code, message):
        print(f"Sora から切断されました: error_code='{error_code}' message='{message}'")
        self._closed = True
        self._connected.clear()

    def _callback(self, indata, frames, time, status):
        self._audio_source.on_data(indata)

    def run(self):
        with sounddevice.InputStream(
            samplerate=self.samplerate,
            channels=self.channels,
            dtype="int16",
            callback=self._callback,
        ):
            self.connect()

            try:
                while self._connected:
                    success, frame = self._video_capture.read()
                    if not success:
                        continue
                    self._video_source.on_captured(frame)
            except KeyboardInterrupt:
                pass
            finally:
                self.disconnect()
                self._video_capture.release()


def sendonly():
    parser = argparse.ArgumentParser()

    # オプション引数の代わりに環境変数による指定も可能。
    # 必須引数
    default_signaling_urls = os.getenv("SORA_SIGNALING_URLS")
    parser.add_argument(
        "--signaling-urls",
        default=default_signaling_urls,
        type=str,
        nargs="+",
        required=not default_signaling_urls,
        help="シグナリング URL",
    )
    default_channel_id = os.getenv("SORA_CHANNEL_ID")
    parser.add_argument(
        "--channel-id",
        default=default_channel_id,
        required=not default_channel_id,
        help="チャネルID",
    )

    # オプション引数
    parser.add_argument(
        "--audio-codec-type",
        default=os.getenv("SORA_AUDIO_CODEC_TYPE"),
        help="音声コーデックの種類",
    )
    parser.add_argument(
        "--video-codec-type",
        default=os.getenv("SORA_VIDEO_CODEC_TYPE"),
        help="映像コーデックの種類",
    )
    parser.add_argument(
        "--video-bit-rate",
        type=int,
        default=int(os.getenv("SORA_VIDEO_BIT_RATE", "500")),
        help="映像ビットレート",
    )
    parser.add_argument("--metadata", default=os.getenv("SORA_METADATA"), help="メタデータ JSON")
    parser.add_argument(
        "--camera-id",
        type=int,
        default=int(os.getenv("SORA_CAMERA_ID", "0")),
        help="cv2.VideoCapture() に渡すカメラ ID",
    )
    parser.add_argument(
        "--video-width",
        type=int,
        default=os.getenv("SORA_VIDEO_WIDTH"),
        help="入力カメラ映像の横幅のヒント",
    )
    parser.add_argument(
        "--video-height",
        type=int,
        default=os.getenv("SORA_VIDEO_HEIGHT"),
        help="入力カメラ映像の高さのヒント",
    )
    parser.add_argument(
        "--openh264", type=str, default=None, help="OpenH264 の共有ライブラリへのパス"
    )
    args = parser.parse_args()

    metadata = {}
    if args.metadata:
        metadata = json.loads(args.metadata)

    sendonly = SendOnly(
        args.signaling_urls,
        args.channel_id,
        metadata,
        args.camera_id,
        args.audio_codec_type,
        args.video_codec_type,
        args.video_bit_rate,
        args.video_width,
        args.video_height,
        args.openh264,
    )
    sendonly.run()


if __name__ == "__main__":
    sendonly()
