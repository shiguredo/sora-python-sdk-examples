import json
import platform
import threading
import time
from threading import Event
from typing import Any

import cv2  # type: ignore
import numpy
import sounddevice  # type: ignore
from helpers import (
    EnvPrefixArgumentParser,
    get_video_codec_preference,
    json_object,
    resolve_channel_id,
)
from numpy import ndarray
from sora_sdk import (
    Sora,
    SoraConnection,
    SoraSignalingErrorCode,
    SoraVideoCodecPreference,
)


class Sendonly:
    def __init__(
        self,
        signaling_urls: list[str],
        channel_id: str,
        /,
        *,
        metadata: dict[str, Any] | None = None,
        audio: bool | None = None,
        video: bool | None = None,
        video_codec_type: str | None = None,
        video_bit_rate: int | None = None,
        data_channel_signaling: bool | None = None,
        openh264_path: str | None = None,
        video_codec_preference: SoraVideoCodecPreference | None = None,
        audio_channels: int = 1,
        audio_sample_rate: int = 16000,
        video_capture: cv2.VideoCapture | None = None,
        show_preview: bool = False,
    ):
        # Sora 接続設定
        self._signaling_urls: list[str] = signaling_urls
        self._channel_id: str = channel_id

        # 音声設定
        self._audio_channels: int = audio_channels
        self._audio_sample_rate: int = audio_sample_rate

        # Sora SDK インスタンス
        self._sora: Sora = Sora(
            video_codec_preference=video_codec_preference,
            openh264=openh264_path,
        )

        # フェイクストリーム用スレッド
        self._fake_audio_thread: threading.Thread | None = None
        self._fake_video_thread: threading.Thread | None = None

        # 音声・映像ソースの生成
        self._audio_source = self._sora.create_audio_source(
            self._audio_channels, self._audio_sample_rate
        )
        self._video_source = self._sora.create_video_source()

        # Sora への接続を作成
        self._connection: SoraConnection = self._sora.create_connection(
            signaling_urls=signaling_urls,
            role="sendonly",
            channel_id=channel_id,
            metadata=metadata,
            audio=audio,
            video=video,
            video_codec_type=video_codec_type,
            video_bit_rate=video_bit_rate,
            data_channel_signaling=data_channel_signaling,
            audio_source=self._audio_source,
            video_source=self._video_source,
        )
        self._connection_id: str | None = None

        # 接続状態管理
        self._connected: Event = Event()
        self._switched: bool = False
        self._closed: Event = Event()
        self._default_connection_timeout_s: float = 10.0

        # コールバック設定
        self._connection.on_set_offer = self._on_set_offer
        self._connection.on_switched = self._on_switched
        self._connection.on_notify = self._on_notify
        self._connection.on_disconnect = self._on_disconnect

        # プレビュー設定
        self._show_preview: bool = show_preview

        # ビデオキャプチャの検証
        if video_capture is not None:
            self._video_capture = video_capture
        else:
            raise ValueError("video_capture must be provided for Sendonly")

    def connect(self, fake_audio=False, fake_video=False) -> None:
        self._connection.connect()

        # フェイク音声スレッドの起動
        if fake_audio:
            self._fake_audio_thread = threading.Thread(target=self._fake_audio_loop, daemon=True)
            self._fake_audio_thread.start()

        # フェイク映像スレッドの起動
        if fake_video:
            self._fake_video_thread = threading.Thread(target=self._fake_video_loop, daemon=True)
            self._fake_video_thread.start()

        # 接続完了を待機
        assert self._connected.wait(self._default_connection_timeout_s), (
            "Could not connect to Sora."
        )

    def disconnect(self) -> None:
        self._connection.disconnect()

    def get_stats(self):
        raw_stats = self._connection.get_stats()
        return json.loads(raw_stats)

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    @property
    def switched(self) -> bool:
        return self._switched

    def _fake_audio_loop(self):
        # 20ms ごとに無音データを送信
        while not self._closed.is_set():
            time.sleep(0.02)
            self._audio_source.on_data(numpy.zeros((320, 1), dtype=numpy.int16))

    def _fake_video_loop(self):
        # 30fps で黒いフレームを送信
        while not self._closed.is_set():
            time.sleep(1.0 / 30)
            self._video_source.on_captured(numpy.zeros((480, 640, 3), dtype=numpy.uint8))

    def _on_set_offer(self, raw_message: str) -> None:
        message: dict[str, Any] = json.loads(raw_message)
        if message["type"] == "offer":
            self._connection_id = message["connection_id"]

    def _on_switched(self, raw_message: str) -> None:
        message = json.loads(raw_message)
        if message["type"] == "switched":
            print(f"Switched to DataChannel Signaling: connection_id={self._connection_id}")
            self._switched = True

    def _on_notify(self, raw_message: str) -> None:
        message: dict[str, Any] = json.loads(raw_message)
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

    def _on_disconnect(self, error_code: SoraSignalingErrorCode, message: str) -> None:
        print(f"Disconnected Sora: error_code='{error_code}' message='{message}'")
        self._connected.clear()
        self._closed.set()

        # フェイクストリームスレッドの終了を待機
        if self._fake_audio_thread is not None:
            self._fake_audio_thread.join(timeout=10)

        if self._fake_video_thread is not None:
            self._fake_video_thread.join(timeout=10)

    def _sounddevice_input_stream_callback(
        self, indata: ndarray, frames: int, time: Any, status: sounddevice.CallbackFlags
    ) -> None:
        self._audio_source.on_data(indata)

    def run(self) -> None:
        # 音声入力ストリームを開始
        with sounddevice.InputStream(
            samplerate=self._audio_sample_rate,
            channels=self._audio_channels,
            dtype="int16",
            callback=self._sounddevice_input_stream_callback,
        ):
            self.connect()
            try:
                while self._connected.is_set():
                    success, frame = self._video_capture.read()
                    if not success:
                        continue
                    self._video_source.on_captured(frame)
                    # プレビュー表示
                    if self._show_preview:
                        cv2.imshow("Sendonly Preview", frame)
                        if cv2.waitKey(1) & 0xFF == ord("q"):
                            break
            except KeyboardInterrupt:
                pass
            finally:
                self.disconnect()
                self._video_capture.release()
                if self._show_preview:
                    cv2.destroyWindow("Sendonly Preview")


def get_video_capture(
    camera_id: int,
    video_width: int,
    video_height: int,
    video_fps: int,
    video_fourcc: str,
) -> cv2.VideoCapture:
    # Windows の場合は CAP_DSHOW を設定しないとカメラの起動が遅くなる
    if platform.system() == "Windows":
        video_capture = cv2.VideoCapture(camera_id, cv2.CAP_DSHOW)
    else:
        video_capture = cv2.VideoCapture(camera_id)

    if video_width is not None:
        video_capture.set(cv2.CAP_PROP_FRAME_WIDTH, video_width)
    if video_height is not None:
        video_capture.set(cv2.CAP_PROP_FRAME_HEIGHT, video_height)
    if video_fourcc is not None:
        video_capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*video_fourcc))
    if video_fps is not None:
        video_capture.set(cv2.CAP_PROP_FPS, video_fps)

    # Ubuntu では FOURCC を設定すると FPS が初期化される
    # Windows では FPS を設定すると FOURCC が初期化される
    # 両方の OS に対応するため、設定が反映されていなければ再設定する
    if video_fourcc is not None:
        fourcc = cv2.VideoWriter_fourcc(*video_fourcc)
        target_fourcc = video_capture.get(cv2.CAP_PROP_FOURCC)
        if fourcc != target_fourcc:
            video_capture.set(cv2.CAP_PROP_FOURCC, fourcc)
    if video_fps is not None:
        if video_fps != int(video_capture.get(cv2.CAP_PROP_FPS)):
            video_capture.set(cv2.CAP_PROP_FPS, video_fps)

    return video_capture


def _parse_args(argv: list[str] | None = None):
    parser = EnvPrefixArgumentParser(
        env_prefix="SORA_",
        description="Sendonly sample that sends video and audio to Sora",
    )
    parser.add_argument(
        "--signaling-url",
        dest="signaling_urls",
        nargs="+",
        metavar="URL",
        help="Sora signaling URL(s). Multiple URLs can be specified (e.g., --signaling-url wss://... --signaling-url wss://...)",
    )
    parser.add_argument(
        "--channel-id",
        dest="channel_id",
        help="Channel ID to connect to",
    )
    parser.add_argument(
        "--channel-id-prefix",
        dest="channel_id_prefix",
        help="Prefix used when generating a channel ID automatically",
    )
    parser.add_argument(
        "--metadata",
        dest="metadata",
        type=json_object,
        help="Metadata to send during connection as a JSON string",
    )
    parser.add_argument(
        "--video-codec-type",
        dest="video_codec_type",
        choices=["VP8", "VP9", "AV1", "H264", "H265"],
        default="VP9",
        help="Video codec type to use for encoding",
    )
    parser.add_argument(
        "--video-bit-rate",
        dest="video_bit_rate",
        type=int,
        default=500,
        help="Video bitrate in kbps (kilobits per second)",
    )
    parser.add_argument(
        "--video-width",
        dest="video_width",
        type=int,
        default=640,
        help="Video frame width in pixels",
    )
    parser.add_argument(
        "--video-height",
        dest="video_height",
        type=int,
        default=360,
        help="Video frame height in pixels",
    )
    parser.add_argument(
        "--video-fps",
        dest="video_fps",
        type=int,
        default=30,
        help="Video frame rate (frames per second)",
    )
    parser.add_argument(
        "--video-fourcc",
        dest="video_fourcc",
        default="MJPG",
        help="Video FOURCC code for camera capture (e.g., MJPG, YUYV)",
    )
    parser.add_argument(
        "--camera-id",
        dest="camera_id",
        type=int,
        default=0,
        help="Camera device ID to use for video capture",
    )
    parser.add_argument(
        "--openh264-path",
        dest="openh264_path",
        help="Path to the OpenH264 library file for H.264 encoding",
    )
    parser.add_argument(
        "--show-preview",
        dest="show_preview",
        action="store_true",
        help="Display a preview window showing the video being sent",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    signaling_urls = args.signaling_urls
    if not signaling_urls:
        raise ValueError("シグナリング URL が指定されていません")

    channel_id = resolve_channel_id(args.channel_id, args.channel_id_prefix)

    camera_id = args.camera_id
    if camera_id is None:
        raise ValueError("カメラ ID を整数で指定してください")

    # OpenCV を利用したビデオキャプチャの設定
    video_capture = get_video_capture(
        camera_id=camera_id,
        video_width=args.video_width,
        video_height=args.video_height,
        video_fps=args.video_fps,
        video_fourcc=args.video_fourcc,
    )

    video_codec_preference = get_video_codec_preference(args.openh264_path)

    sendonly_instance = Sendonly(
        signaling_urls,
        channel_id,
        metadata=args.metadata,
        video_codec_type=args.video_codec_type,
        video_bit_rate=args.video_bit_rate,
        openh264_path=args.openh264_path,
        video_codec_preference=video_codec_preference,
        video_capture=video_capture,
        show_preview=args.show_preview,
    )
    sendonly_instance.run()


if __name__ == "__main__":
    main()
