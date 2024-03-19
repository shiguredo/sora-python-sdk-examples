import argparse
import json
import os
from threading import Event
from typing import Any, Dict, List, Optional

import cv2
import sounddevice
from dotenv import load_dotenv
from numpy import ndarray
from sora_sdk import Sora, SoraConnection, SoraSignalingErrorCode


class SendOnly:
    def __init__(
        self,
        # python 3.8 まで対応なので list[str] ではなく List[str] にする
        signaling_urls: List[str],
        channel_id: str,
        metadata: Optional[Dict[str, Any]],
        camera_id: int,
        video_codec_type: str,
        video_bit_rate: int,
        video_width: Optional[int],
        video_height: Optional[int],
        openh264: Optional[str],
        audio_channels: int = 1,
        audio_sample_rate: int = 16000,
    ):
        self.audio_channels = audio_channels
        self.audio_sample_rate = audio_sample_rate

        self._sora: Sora = Sora(openh264=openh264)

        self._audio_source = self._sora.create_audio_source(
            self.audio_channels, self.audio_sample_rate
        )
        self._video_source = self._sora.create_video_source()

        self._connection: SoraConnection = self._sora.create_connection(
            signaling_urls=signaling_urls,
            role="sendonly",
            channel_id=channel_id,
            metadata=metadata,
            video_codec_type=video_codec_type,
            video_bit_rate=video_bit_rate,
            audio_source=self._audio_source,
            video_source=self._video_source,
        )
        self._connection_id = ""
        self._connected = Event()
        self._closed = False
        self._default_connection_timeout_s = 10.0

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

        assert self._connected.wait(
            timeout=self._default_connection_timeout_s
        ), "接続がタイムアウトしました"

    def disconnect(self):
        self._connection.disconnect()

    def _on_notify(self, raw_message: str):
        message: Dict[str, Any] = json.loads(raw_message)
        # "type": "notify" の "connection.created" で通知される connection_id が
        # 自分の connection_id と一致する場合に接続完了とする
        if (
            message["type"] == "notify"
            and message["event_type"] == "connection.created"
            and message["connection_id"] == self._connection_id
        ):
            print("Sora に接続しました")
            self._connected.set()

    def _on_set_offer(self, raw_message: str):
        message: Dict[str, Any] = json.loads(raw_message)
        if message["type"] == "offer":
            # "type": "offer" に入ってくる自分の connection_id を保存する
            self._connection_id = message["connection_id"]

    def _on_disconnect(self, error_code: SoraSignalingErrorCode, message: str):
        print(f"Sora から切断されました: error_code='{error_code}' message='{message}'")
        self._connected.clear()
        self._closed = True

    def _callback(self, indata: ndarray, frames: int, time, status: sounddevice.CallbackFlags):
        self._audio_source.on_data(indata)

    def run(self):
        # 音声デバイスの入力を Sora に送信する設定
        with sounddevice.InputStream(
            samplerate=self.audio_sample_rate,
            channels=self.audio_channels,
            dtype="int16",
            callback=self._callback,
        ):
            self.connect()
            try:
                while self._connected.is_set():
                    # 取得したフレームを Sora に送信する
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
    # .env ファイルを読み込む
    load_dotenv()
    parser = argparse.ArgumentParser()

    # 必須引数
    default_signaling_urls = None
    if urls := os.getenv("SORA_SIGNALING_URLS"):
        # SORA_SIGNALING_URLS 環境変数はカンマ区切りで複数指定可能
        default_signaling_urls = urls.split(",")
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
        "--video-codec-type",
        # Sora のデフォルト値と合わせる
        default=os.getenv("SORA_VIDEO_CODEC_TYPE", "VP9"),
        help="映像コーデックの種類",
    )
    parser.add_argument(
        "--video-bit-rate",
        type=int,
        # Sora のデフォルト値と合わせる
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
        default=int(os.getenv("SORA_VIDEO_WIDTH", "640")),
        help="入力カメラ映像の横幅のヒント",
    )
    parser.add_argument(
        "--video-height",
        type=int,
        default=int(os.getenv("SORA_VIDEO_HEIGHT", "360")),
        help="入力カメラ映像の高さのヒント",
    )
    parser.add_argument(
        "--openh264", type=str, default=None, help="OpenH264 の共有ライブラリへのパス"
    )
    args = parser.parse_args()

    # metadata は JSON 形式で指定するので一同 JSON 形式で読み込む
    metadata = None
    if args.metadata:
        metadata = json.loads(args.metadata)

    sendonly = SendOnly(
        args.signaling_urls,
        args.channel_id,
        metadata,
        args.camera_id,
        args.video_codec_type,
        args.video_bit_rate,
        args.video_width,
        args.video_height,
        args.openh264,
    )
    sendonly.run()


if __name__ == "__main__":
    sendonly()
