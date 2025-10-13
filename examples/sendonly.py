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
    """
    Sora にビデオと音声ストリームを送信するためのクラス。

    このクラスは Sora への接続を設定し、カメラからのビデオと
    マイクからの音声を Sora に送信するメソッドを提供します。
    """

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
        """
        Sendonly インスタンスを初期化します。

        :param signaling_urls: Sora シグナリング URL のリスト
        :param channel_id: 接続するチャンネル ID
        :param metadata: 接続のためのオプションのメタデータ
        :param audio: 音声ストリームを送信するかどうか
        :param video: ビデオストリームを送信するかどうか
        :param video_codec_type: 使用するビデオコーデックの種類
        :param video_bit_rate: ビデオのビットレート
        :param openh264_path: OpenH264 ライブラリへのパス
        :param audio_channels: 音声チャンネル数（デフォルト: 1）
        :param audio_sample_rate: 音声サンプリングレート（デフォルト: 16000）
        :param video_capture: カメラからのビデオキャプチャ
        """
        self._signaling_urls: list[str] = signaling_urls
        self._channel_id: str = channel_id

        self._audio_channels: int = audio_channels
        self._audio_sample_rate: int = audio_sample_rate

        self._sora: Sora = Sora(
            video_codec_preference=video_codec_preference,
            openh264=openh264_path,
        )

        self._fake_audio_thread: threading.Thread | None = None
        self._fake_video_thread: threading.Thread | None = None

        self._audio_source = self._sora.create_audio_source(
            self._audio_channels, self._audio_sample_rate
        )
        self._video_source = self._sora.create_video_source()

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

        self._connected: Event = Event()
        self._switched: bool = False
        self._closed: Event = Event()
        self._default_connection_timeout_s: float = 10.0

        self._connection.on_set_offer = self._on_set_offer
        self._connection.on_switched = self._on_switched
        self._connection.on_notify = self._on_notify
        self._connection.on_disconnect = self._on_disconnect

        self._show_preview: bool = show_preview

        if video_capture is not None:
            self._video_capture = video_capture
        else:
            raise ValueError("video_capture must be provided for Sendonly")

    def connect(self, fake_audio=False, fake_video=False) -> None:
        """
        Sora への接続を確立します。

        :raises AssertionError: タイムアウト期間内に接続が確立できなかった場合
        """
        self._connection.connect()

        if fake_audio:
            self._fake_audio_thread = threading.Thread(target=self._fake_audio_loop, daemon=True)
            self._fake_audio_thread.start()

        if fake_video:
            self._fake_video_thread = threading.Thread(target=self._fake_video_loop, daemon=True)
            self._fake_video_thread.start()

        assert self._connected.wait(self._default_connection_timeout_s), (
            "Could not connect to Sora."
        )

    def disconnect(self) -> None:
        """Sora から切断します。"""
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
        while not self._closed.is_set():
            time.sleep(0.02)
            self._audio_source.on_data(numpy.zeros((320, 1), dtype=numpy.int16))

    def _fake_video_loop(self):
        while not self._closed.is_set():
            time.sleep(1.0 / 30)
            self._video_source.on_captured(numpy.zeros((480, 640, 3), dtype=numpy.uint8))

    def _on_set_offer(self, raw_message: str) -> None:
        """
        オファー設定イベントを処理します。

        :param raw_message: オファーを含む生のメッセージ
        """
        message: dict[str, Any] = json.loads(raw_message)
        if message["type"] == "offer":
            self._connection_id = message["connection_id"]

    def _on_switched(self, raw_message: str) -> None:
        message = json.loads(raw_message)
        if message["type"] == "switched":
            print(f"Switched to DataChannel Signaling: connection_id={self._connection_id}")
            self._switched = True

    def _on_notify(self, raw_message: str) -> None:
        """
        Sora からの通知イベントを処理します。

        :param raw_message: 生の通知メッセージ
        """
        message: dict[str, Any] = json.loads(raw_message)
        if (
            message["type"] == "notify"
            and message["event_type"] == "connection.created"
            and message["connection_id"] == self._connection_id
        ):
            print(f"Connected Sora: channel_id={self._channel_id}, connection_id={self._connection_id}")
            self._connected.set()

    def _on_disconnect(self, error_code: SoraSignalingErrorCode, message: str) -> None:
        """
        切断イベントを処理します。

        :param error_code: 切断のエラーコード
        :param message: 切断メッセージ
        """
        print(f"Disconnected Sora: error_code='{error_code}' message='{message}'")
        self._connected.clear()
        self._closed.set()

        if self._fake_audio_thread is not None:
            self._fake_audio_thread.join(timeout=10)

        if self._fake_video_thread is not None:
            self._fake_video_thread.join(timeout=10)

    def _sounddevice_input_stream_callback(
        self, indata: ndarray, frames: int, time: Any, status: sounddevice.CallbackFlags
    ) -> None:
        """
        音声入力のためのコールバック関数。

        :param indata: 入力された音声データ
        :param frames: 処理するフレーム数
        :param time: タイミング情報（未使用）
        :param status: ステータスフラグ
        """
        self._audio_source.on_data(indata)

    def run(self) -> None:
        """
        ビデオフレームの送信と音声の送信を行うメインループ。
        """
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
    """
    ビデオキャプチャの設定を行います。

    :param camera_id: 使用するカメラの ID
    :param video_width: ビデオの幅
    :param video_height: ビデオの高さ
    :param video_fps: ビデオのフレームレート
    :param video_fourcc: ビデオの FOURCC コード
    """

    if platform.system() == "Windows":
        # CAP_DSHOW を設定しないと、カメラの起動がめちゃめちゃ遅くなる
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

    # Ubuntu → FOURCC を設定すると FPS が初期化される
    # Windows → FPS を設定すると FOURCC が初期化される
    # ので、両方に対応するため２回設定する
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
        description="Sora に対して映像と音声を送信する sendonly サンプル",
    )
    parser.add_argument(
        "--signaling-url",
        dest="signaling_urls",
        nargs="+",
        metavar="URL",
        help="Sora シグナリング URL。複数指定可（例: --signaling-url wss://... --signaling-url wss://...）。",
    )
    parser.add_argument("--channel-id", dest="channel_id", help="接続するチャンネル ID")
    parser.add_argument(
        "--channel-id-prefix",
        dest="channel_id_prefix",
        help="チャンネル ID を生成する際に利用するプレフィックス",
    )
    parser.add_argument(
        "--metadata",
        dest="metadata",
        type=json_object,
        help="接続時に送信する JSON 文字列",
    )
    parser.add_argument(
        "--video-codec-type",
        dest="video_codec_type",
        choices=["VP8", "VP9", "AV1", "H264", "H265"],
        default="VP9",
        help="使用するビデオコーデックの種類",
    )
    parser.add_argument(
        "--video-bit-rate",
        dest="video_bit_rate",
        type=int,
        default=500,
        help="ビデオのビットレート (kbps)",
    )
    parser.add_argument(
        "--video-width",
        dest="video_width",
        type=int,
        default=640,
        help="ビデオの幅",
    )
    parser.add_argument(
        "--video-height",
        dest="video_height",
        type=int,
        default=360,
        help="ビデオの高さ",
    )
    parser.add_argument(
        "--video-fps",
        dest="video_fps",
        type=int,
        default=30,
        help="ビデオのフレームレート",
    )
    parser.add_argument(
        "--video-fourcc",
        dest="video_fourcc",
        default="MJPG",
        help="ビデオの FOURCC コード",
    )
    parser.add_argument(
        "--camera-id",
        dest="camera_id",
        type=int,
        default=0,
        help="使用するカメラの ID",
    )
    parser.add_argument("--openh264-path", dest="openh264_path", help="OpenH264 ライブラリへのパス")
    parser.add_argument(
        "--show-preview",
        dest="show_preview",
        action="store_true",
        help="送信中の映像をプレビュー表示します",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """
    コマンドライン引数を設定しておき、必要に応じて環境変数で上書きしながら
    Sendonly インスタンスを構築し実行します。
    """
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
