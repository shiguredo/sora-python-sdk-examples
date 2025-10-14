import json
import platform
import time
from pathlib import Path
from threading import Event
from typing import Sequence

import cv2  # type: ignore
import jwt  # type: ignore
import mediapipe as mp  # type: ignore
from cv2.typing import MatLike  # type: ignore
from mediapipe.tasks import python  # type: ignore
from mediapipe.tasks.python import vision  # type: ignore
from sora_sdk import Sora, SoraSignalingErrorCode, SoraVideoSource

from helpers import EnvPrefixArgumentParser, resolve_channel_id


# 物体検出を行い、検出結果を WebRTC で送信するクラス
class ObjectDetectionStreamer:
    def __init__(
        self,
        signaling_urls: list[str],
        role: str,
        channel_id: str,
        access_token: str | None,
        camera_id: int,
        video_width: int | None,
        video_height: int | None,
        video_fps: int | None,
        video_fourcc: str | None,
        model_path: Path,
        score_threshold: float,
        max_results: int,
        category_allowlist: Sequence[str] | None,
    ):
        # チャンネル ID
        self._channel_id: str = channel_id

        # Sora SDK の初期化
        self._sora = Sora(openh264=None)
        self._video_source: SoraVideoSource = self._sora.create_video_source()
        self._connection = self._sora.create_connection(
            signaling_urls=signaling_urls,
            role=role,
            channel_id=channel_id,
            metadata={"access_token": access_token} if access_token else None,
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

        # 物体検出の設定
        self._model_path = model_path
        self._score_threshold = score_threshold
        self._max_results = max_results
        self._category_allowlist = list(category_allowlist) if category_allowlist else None

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
            self._video_capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*video_fourcc))
        if video_fps is not None:
            self._video_capture.set(cv2.CAP_PROP_FPS, video_fps)

        # Ubuntu → FOURCC を設定すると FPS が初期化される
        # Windows → FPS を設定すると FOURCC が初期化される
        # ので、両方に対応するため 2 回設定する
        if video_fourcc is not None:
            fourcc = cv2.VideoWriter_fourcc(*video_fourcc)
            target_fourcc = self._video_capture.get(cv2.CAP_PROP_FOURCC)
            if fourcc != target_fourcc:
                self._video_capture.set(cv2.CAP_PROP_FOURCC, fourcc)
        if video_fps is not None:
            if video_fps != int(self._video_capture.get(cv2.CAP_PROP_FPS)):
                self._video_capture.set(cv2.CAP_PROP_FPS, video_fps)

    def _create_object_detector(self) -> vision.ObjectDetector:
        base_options = python.BaseOptions(model_asset_path=str(self._model_path))
        options = vision.ObjectDetectorOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.IMAGE,
            score_threshold=self._score_threshold,
            max_results=self._max_results,
            category_allowlist=self._category_allowlist,
        )
        return vision.ObjectDetector.create_from_options(options)

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
        detector = self._create_object_detector()
        try:
            while self._connected.is_set() and self._video_capture.isOpened():
                success, frame = self._video_capture.read()
                if not success:
                    continue
                annotated_frame = self.run_one_frame(detector, frame)
                self._video_source.on_captured(annotated_frame)
        except KeyboardInterrupt:
            pass
        finally:
            detector.close()
            self.disconnect()
            self._video_capture.release()

    def run_one_frame(
        self,
        detector: vision.ObjectDetector,
        frame: MatLike,  # type: ignore
    ) -> MatLike:  # type: ignore
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        detection_result = detector.detect(mp_image)
        return self._annotate_frame(frame, detection_result)

    def _annotate_frame(
        self,
        frame: MatLike,  # type: ignore
        detection_result: vision.ObjectDetectorResult,
    ) -> MatLike:  # type: ignore
        annotated_frame = frame.copy()
        frame_height, frame_width, _ = annotated_frame.shape
        for detection in detection_result.detections:
            bbox = detection.bounding_box
            x = max(0, min(int(bbox.origin_x), frame_width - 1))
            y = max(0, min(int(bbox.origin_y), frame_height - 1))
            w = max(0, min(int(bbox.width), frame_width - x))
            h = max(0, min(int(bbox.height), frame_height - y))
            x2 = min(frame_width - 1, x + w)
            y2 = min(frame_height - 1, y + h)

            cv2.rectangle(annotated_frame, (x, y), (x2, y2), (0, 255, 0), 2)

            if not detection.categories:
                continue
            category = detection.categories[0]
            name = category.category_name or "unknown"
            score = category.score if category.score is not None else 0.0
            label = f"{name}: {score:.2f}"

            (text_width, text_height), baseline = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
            )
            text_x = x
            text_y = max(0, y - text_height - baseline)
            cv2.rectangle(
                annotated_frame,
                (text_x, text_y),
                (text_x + text_width, text_y + text_height + baseline),
                (0, 255, 0),
                cv2.FILLED,
            )
            cv2.putText(
                annotated_frame,
                label,
                (text_x, text_y + text_height),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 0, 0),
                1,
                cv2.LINE_AA,
            )
        return annotated_frame


def _parse_args(argv: list[str] | None = None):
    parser = EnvPrefixArgumentParser(
        env_prefix="SORA_",
        description="Sora sendonly example with object detection overlay",
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
    parser.add_argument(
        "--model-path",
        dest="model_path",
        required=True,
        help="Filesystem path to the Mediapipe object detection TFLite model. For example, provide efficientdet_lite0.tflite downloaded from https://developers.google.com/mediapipe/solutions/vision/object_detector",
    )
    parser.add_argument(
        "--score-threshold",
        dest="score_threshold",
        type=float,
        default=0.5,
        help="Minimum confidence score for detected objects to be rendered. Default is 0.5",
    )
    parser.add_argument(
        "--max-results",
        dest="max_results",
        type=int,
        default=5,
        help="Maximum number of detection results to return per frame. Default is 5",
    )
    parser.add_argument(
        "--category-allowlist",
        dest="category_allowlist",
        nargs="+",
        help="Optional list of category names to keep in detection results. Provide names separated by spaces, for example: --category-allowlist person bicycle car",
    )
    parser.add_argument(
        "--secret-key",
        dest="secret_key",
        help="Shared secret used to mint an access token. The script generates an HS256 JWT that embeds the resolved channel ID in its claims.",
    )
    return parser.parse_args(argv)


def _create_access_token(secret_key: str, channel_id: str) -> str:
    # JWT に有効期限を付与し、チャンネル ID を埋め込む
    now = int(time.time())
    payload = {
        "iss": "sora-python-sdk-examples",
        "iat": now,
        "exp": now + 3600,
        "channel_id": channel_id,
    }
    return jwt.encode(payload, secret_key, algorithm="HS256")


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    signaling_urls = args.signaling_urls
    if not signaling_urls:
        raise ValueError("Signaling URL is not specified")

    channel_id = resolve_channel_id(args.channel_id, args.channel_id_prefix)

    if args.camera_id is None:
        raise ValueError("Camera ID must be specified as an integer")

    model_path = Path(args.model_path)
    if not model_path.exists():
        raise FileNotFoundError(
            f"Model file not found at '{model_path}'. Please download a Mediapipe compatible TFLite model and provide its path using --model-path"
        )

    secret_key = args.secret_key
    if not secret_key:
        raise ValueError(
            "Secret key is not specified. Provide --secret-key or set SORA_SECRET_KEY."
        )
    access_token = _create_access_token(secret_key, channel_id)

    streamer = ObjectDetectionStreamer(
        signaling_urls=signaling_urls,
        role="sendonly",
        channel_id=channel_id,
        access_token=access_token,
        camera_id=args.camera_id,
        video_height=args.video_height,
        video_width=args.video_width,
        video_fps=args.video_fps,
        video_fourcc=args.video_fourcc,
        model_path=model_path,
        score_threshold=args.score_threshold,
        max_results=args.max_results,
        category_allowlist=args.category_allowlist,
    )
    streamer.run()


if __name__ == "__main__":
    main()
