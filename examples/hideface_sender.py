import json
import math
import platform
from pathlib import Path
from threading import Event
from typing import Any

import cv2
import mediapipe as mp
import numpy as np
from cv2.typing import MatLike
from PIL import Image
from sora_sdk import Sora, SoraSignalingErrorCode, SoraVideoSource

from helpers import (
    EnvPrefixArgumentParser,
    as_uint8_frame,
    json_object,
    resolve_channel_id,
    video_writer_fourcc,
)


# 顔検出を行い、検出された顔にロゴを重ねて Sora に送信するクラス
class LogoStreamer:
    def __init__(
        self,
        signaling_urls: list[str],
        role: str,
        channel_id: str,
        metadata: dict[str, Any] | None,
        camera_id: int,
        video_width: int | None,
        video_height: int | None,
        video_fps: int | None,
        video_fourcc: str | None,
    ):
        # MediaPipe の顔検出モジュール
        self.mp_face_detection = mp.solutions.face_detection

        # チャンネル ID
        self._channel_id: str = channel_id

        # Sora SDK の初期化
        self._sora = Sora(openh264=None)
        self._video_source: SoraVideoSource = self._sora.create_video_source()
        self._connection = self._sora.create_connection(
            signaling_urls=signaling_urls,
            role=role,
            channel_id=channel_id,
            metadata=metadata,
            video_codec_type=None,
            video_bit_rate=500,
            video_source=self._video_source,
        )
        self._connection_id: str | None = None

        # 接続状態管理
        self._connected: Event = Event()
        self._closed: bool = False
        self._default_connection_timeout_s: float = 10.0

        # コールバック設定
        self._connection.on_set_offer = self._on_set_offer
        self._connection.on_notify = self._on_notify
        self._connection.on_disconnect = self._on_disconnect

        # カメラの初期化
        self._setup_video_capture(camera_id, video_width, video_height, video_fps, video_fourcc)

        # ロゴを読み込む
        self._logo = Image.open(Path(__file__).parent.joinpath("shiguremaru.png"))

    def _setup_video_capture(
        self,
        camera_id: int,
        video_width: int | None,
        video_height: int | None,
        video_fps: int | None,
        video_fourcc: str | None,
    ) -> None:
        # CAP_DSHOW を設定しないと、カメラの起動がめちゃめちゃ遅くなる
        if platform.system() == "Windows":
            self._video_capture = cv2.VideoCapture(camera_id, cv2.CAP_DSHOW)
        else:
            self._video_capture = cv2.VideoCapture(camera_id)

        if video_width is not None:
            self._video_capture.set(cv2.CAP_PROP_FRAME_WIDTH, video_width)
        if video_height is not None:
            self._video_capture.set(cv2.CAP_PROP_FRAME_HEIGHT, video_height)
        if video_fourcc is not None:
            self._video_capture.set(cv2.CAP_PROP_FOURCC, video_writer_fourcc(*video_fourcc))
        if video_fps is not None:
            self._video_capture.set(cv2.CAP_PROP_FPS, video_fps)

        # Ubuntu → FOURCC を設定すると FPS が初期化される
        # Windows → FPS を設定すると FOURCC が初期化される
        # ので、両方に対応するため 2 回設定する
        if video_fourcc is not None:
            fourcc = video_writer_fourcc(*video_fourcc)
            target_fourcc = self._video_capture.get(cv2.CAP_PROP_FOURCC)
            if fourcc != target_fourcc:
                self._video_capture.set(cv2.CAP_PROP_FOURCC, fourcc)
        if video_fps is not None:
            if video_fps != int(self._video_capture.get(cv2.CAP_PROP_FPS)):
                self._video_capture.set(cv2.CAP_PROP_FPS, video_fps)

    def connect(self) -> None:
        self._connection.connect()

        assert self._connected.wait(timeout=self._default_connection_timeout_s), "Failed to connect"

    def disconnect(self) -> None:
        self._connection.disconnect()

    def _on_disconnect(self, error_code: SoraSignalingErrorCode, message: str) -> None:
        print(f"Sora から切断されました: error_code='{error_code}' message='{message}'")
        self._connected.clear()
        self._closed = True

    def _on_set_offer(self, raw_message: str) -> None:
        message = json.loads(raw_message)
        if message["type"] == "offer":
            self._connection_id = message["connection_id"]

    def _on_notify(self, raw_message: str) -> None:
        message = json.loads(raw_message)
        if (
            message["type"] == "notify"
            and message["event_type"] == "connection.created"
            and message["connection_id"] == self._connection_id
        ):
            print(
                f"Connected Sora: channel_id={self._channel_id}, connection_id={self._connection_id}"
            )
            self._connected.set()

    def run(self) -> None:
        self.connect()
        try:
            # 顔検出を用意する
            with self.mp_face_detection.FaceDetection(
                model_selection=0, min_detection_confidence=0.5
            ) as face_detection:
                angle = 0
                while self._connected.is_set() and self._video_capture.isOpened():
                    success, frame = self._video_capture.read()
                    if not success:
                        continue
                    angle = self.run_one_frame(face_detection, angle, frame)
        except KeyboardInterrupt:
            pass
        finally:
            self.disconnect()
            self._video_capture.release()

    def run_one_frame(
        self,
        face_detection: mp.solutions.face_detection.FaceDetection,
        angle: int,
        frame: MatLike,
    ) -> int:
        # 高速化の呪文
        frame.flags.writeable = False
        # MediaPipe や PIL で処理できるように色の順序を変える
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # MediaPipe で顔を検出する
        results = face_detection.process(frame)

        frame_height, frame_width, _ = frame.shape
        # PIL で処理できるように画像を変換する
        pil_image = Image.fromarray(frame)

        # ロゴを回しておく
        rotated_logo = self._logo.rotate(angle)
        angle += 1
        if angle >= 360:
            angle = 0

        if results.detections:
            for detection in results.detections:
                location = detection.location_data
                if not location.HasField("relative_bounding_box"):
                    continue
                bb = location.relative_bounding_box

                # 正規化されているので逆正規化を行う
                w_px = math.floor(bb.width * frame_width)
                h_px = math.floor(bb.height * frame_height)
                x_px = min(math.floor(bb.xmin * frame_width), frame_width - 1)
                y_px = min(math.floor(bb.ymin * frame_height), frame_height - 1)

                # 検出領域は顔に対して小さいため、顔全体が覆われるように検出領域を大きくする
                fixed_w_px = math.floor(w_px * 1.6)
                fixed_h_px = math.floor(h_px * 1.6)
                # 大きくした分、座標がずれてしまうため顔の中心になるように座標を補正する
                fixed_x_px = max(0, math.floor(x_px - (fixed_w_px - w_px) / 2))
                # 検出領域は顔であり頭が入っていないため、上寄りになるように座標を補正する
                fixed_y_px = max(0, math.floor(y_px - (fixed_h_px - h_px)))

                # ロゴをリサイズする
                resized_logo = rotated_logo.resize((fixed_w_px, fixed_h_px))
                pil_image.paste(resized_logo, (fixed_x_px, fixed_y_px), resized_logo)

        frame.flags.writeable = True
        # PIL から NumPy に画像を戻す
        frame = np.array(pil_image)
        # 色の順序をもとに戻す
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

        # WebRTC に渡す
        self._video_source.on_captured(as_uint8_frame(frame))
        return angle


def _parse_args(argv: list[str] | None = None):
    parser = EnvPrefixArgumentParser(
        env_prefix="SORA_",
        description="Sora sendonly example with face detection and logo overlay",
    )
    parser.add_argument(
        "--signaling-url",
        dest="signaling_urls",
        nargs="+",
        metavar="URL",
        help="Sora signaling URL(s). Multiple URLs can be specified using the format: --signaling-url wss://example1.com --signaling-url wss://example2.com",
    )
    parser.add_argument(
        "--channel-id",
        dest="channel_id",
        help="Sora channel ID to connect to. If not specified, --channel-id-prefix must be provided to generate a channel ID",
    )
    parser.add_argument(
        "--channel-id-prefix",
        dest="channel_id_prefix",
        help="Prefix string used to generate a unique channel ID. A random suffix will be appended to this prefix",
    )
    parser.add_argument(
        "--metadata",
        dest="metadata",
        type=json_object,
        help='JSON string to be sent as metadata during Sora connection establishment. Must be valid JSON format (e.g., \'{"key": "value"}\')',
    )
    parser.add_argument(
        "--camera-id",
        dest="camera_id",
        type=int,
        default=1,
        help="Camera device ID to use for video capture. Default is 1. Use 0 for the primary camera, 1 for secondary camera, etc.",
    )
    parser.add_argument(
        "--video-width",
        dest="video_width",
        type=int,
        default=640,
        help="Width of the video stream in pixels. Default is 640",
    )
    parser.add_argument(
        "--video-height",
        dest="video_height",
        type=int,
        default=360,
        help="Height of the video stream in pixels. Default is 360",
    )
    parser.add_argument(
        "--video-fps",
        dest="video_fps",
        type=int,
        default=30,
        help="Frame rate of the video stream in frames per second. Default is 30",
    )
    parser.add_argument(
        "--video-fourcc",
        dest="video_fourcc",
        default="MJPG",
        help="FourCC code for video compression format. Default is 'MJPG' (Motion JPEG). Other common options include 'YUYV', 'H264', etc.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    signaling_urls = args.signaling_urls
    if not signaling_urls:
        raise ValueError("Signaling URL is not specified")

    channel_id = resolve_channel_id(args.channel_id, args.channel_id_prefix)

    if args.camera_id is None:
        raise ValueError("Camera ID must be specified as an integer")

    streamer = LogoStreamer(
        signaling_urls=signaling_urls,
        role="sendonly",
        channel_id=channel_id,
        metadata=args.metadata,
        camera_id=args.camera_id,
        video_height=args.video_height,
        video_width=args.video_width,
        video_fps=args.video_fps,
        video_fourcc=args.video_fourcc,
    )
    streamer.run()


if __name__ == "__main__":
    main()
