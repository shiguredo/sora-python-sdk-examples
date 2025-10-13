import json
import math
from threading import Event, Lock
from typing import Any

import cv2  # type: ignore
import numpy as np
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
    SoraAudioSink,
    SoraConnection,
    SoraMediaTrack,
    SoraSignalingErrorCode,
    SoraVideoCodecPreference,
    SoraVideoFrame,
    SoraVideoSink,
)


class Recvonly:
    def __init__(
        self,
        signaling_urls: list[str],
        channel_id: str,
        /,
        *,
        metadata: dict[str, Any] | None = None,
        data_channel_signaling: bool | None = None,
        openh264_path: str | None = None,
        video_codec_preference: SoraVideoCodecPreference | None = None,
        output_frequency: int = 16000,
        output_channels: int = 1,
        grid_cols: int = 3,
    ):
        self._signaling_urls: list[str] = signaling_urls
        self._channel_id: str = channel_id

        # 音声出力設定
        self._output_frequency: int = output_frequency
        self._output_channels: int = output_channels

        # グリッド表示設定
        self._grid_cols: int = grid_cols

        # Sora 接続
        self._sora: Sora = Sora(
            openh264=openh264_path, video_codec_preference=video_codec_preference
        )
        self._connection: SoraConnection = self._sora.create_connection(
            signaling_urls=signaling_urls,
            role="recvonly",
            channel_id=channel_id,
            metadata=metadata,
            data_channel_signaling=data_channel_signaling,
        )
        self._connection_id: str | None = None

        # 接続状態管理
        self._connected: Event = Event()
        self._switched: bool = False
        self._closed: Event = Event()
        self._default_connection_timeout_s: float = 10.0

        # 音声・映像シンク
        self._audio_sink: SoraAudioSink | None = None
        self._video_sinks: dict[str, SoraVideoSink] = {}

        # connection_id をキーとしてフレームを管理
        self._video_frames: dict[str, np.ndarray] = {}
        self._video_frames_lock: Lock = Lock()

        # track_id から connection_id へのマッピング
        self._track_to_connection: dict[str, str] = {}

        # connection_id の出現順序を記録（グリッド位置を固定するため）
        self._connection_order: list[str] = []

        self._connection.on_set_offer = self._on_set_offer
        self._connection.on_switched = self._on_switched
        self._connection.on_notify = self._on_notify
        self._connection.on_disconnect = self._on_disconnect
        self._connection.on_track = self._on_track

    def connect(self) -> None:
        self._connection.connect()

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

    @property
    def closed(self):
        return self._closed.is_set()

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

        if message["type"] == "notify":
            event_type = message.get("event_type")
            connection_id = message.get("connection_id")

            # 接続作成イベント
            if event_type == "connection.created":
                if connection_id == self._connection_id:
                    # 自分の接続の場合
                    print(
                        f"Connected Sora: channel_id={self._channel_id}, connection_id={self._connection_id}"
                    )
                    self._connected.set()
                else:
                    # 他の接続の場合、順序を記録
                    with self._video_frames_lock:
                        if connection_id not in self._connection_order:
                            self._connection_order.append(connection_id)
                            print(f"New connection detected: connection_id={connection_id}")

            # 接続切断イベント
            elif event_type == "connection.destroyed":
                if connection_id and connection_id != self._connection_id:
                    with self._video_frames_lock:
                        # フレームを削除
                        if connection_id in self._video_frames:
                            del self._video_frames[connection_id]

                        # 順序から削除
                        if connection_id in self._connection_order:
                            self._connection_order.remove(connection_id)

                        # 関連する track と sink を削除
                        tracks_to_remove = [
                            track_id
                            for track_id, conn_id in self._track_to_connection.items()
                            if conn_id == connection_id
                        ]
                        for track_id in tracks_to_remove:
                            del self._track_to_connection[track_id]
                            if track_id in self._video_sinks:
                                del self._video_sinks[track_id]

                        print(f"Connection removed: connection_id={connection_id}")

    def _on_disconnect(self, error_code: SoraSignalingErrorCode, message: str) -> None:
        print(f"Disconnected Sora: error_code='{error_code}' message='{message}'")
        self._connected.clear()
        self._closed.is_set()

    def _create_video_frame_callback(self, connection_id: str):
        def callback(frame: SoraVideoFrame) -> None:
            with self._video_frames_lock:
                # frame.data() のコピーを作成して保存（バッファ共有を防ぐ）
                self._video_frames[connection_id] = frame.data().copy()

        return callback

    def _on_track(self, track: SoraMediaTrack) -> None:
        # 音声トラック
        if track.kind == "audio":
            self._audio_sink = SoraAudioSink(track, self._output_frequency, self._output_channels)

        # ビデオトラック
        if track.kind == "video":
            track_id = track.id

            # track_id から connection_id を抽出
            # 例: "J2ZJCZK9R90KDDN7CDNPS8FMR4-video" -> "J2ZJCZK9R90KDDN7CDNPS8FMR4"
            if "-" not in track_id:
                raise ValueError(
                    f"Invalid track_id format: {track_id}. Expected format: 'connection_id-video'"
                )

            connection_id = track_id.rsplit("-", 1)[0]

            # マッピングを保存
            self._track_to_connection[track_id] = connection_id

            # connection_id の順序を記録
            with self._video_frames_lock:
                if connection_id not in self._connection_order:
                    self._connection_order.append(connection_id)

            # video sink を作成
            video_sink = SoraVideoSink(track)
            video_sink.on_frame = self._create_video_frame_callback(connection_id)
            self._video_sinks[track_id] = video_sink
            print(f"Video track added: track_id={track_id}, connection_id={connection_id}")

    def _create_grid_image(
        self,
        frames_dict: dict[str, np.ndarray],
        connection_order: list[str],
        cell_width: int = 320,
        cell_height: int = 240,
    ) -> np.ndarray | None:
        if not frames_dict:
            return None

        # connection_order に基づいてフレームを順序付け（フレームが存在するもののみ）
        ordered_items = [
            (conn_id, frames_dict[conn_id])
            for conn_id in connection_order
            if conn_id in frames_dict
        ]

        if not ordered_items:
            return None

        num_frames = len(ordered_items)

        # グリッドの行数と列数を計算
        cols = min(self._grid_cols, num_frames)
        rows = math.ceil(num_frames / cols)

        # パディング
        padding = 5

        # グリッド全体のサイズを計算
        grid_width = cols * cell_width + (cols + 1) * padding
        grid_height = rows * cell_height + (rows + 1) * padding

        # 黒い背景の画像を作成
        grid_image = np.zeros((grid_height, grid_width, 3), dtype=np.uint8)

        # 各フレームをグリッドに配置
        for idx, (connection_id, frame) in enumerate(ordered_items):
            row = idx // cols
            col = idx % cols

            # フレームをリサイズ
            resized_frame = cv2.resize(frame, (cell_width, cell_height))

            # 配置位置を計算
            y_start = row * cell_height + (row + 1) * padding
            y_end = y_start + cell_height
            x_start = col * cell_width + (col + 1) * padding
            x_end = x_start + cell_width

            # フレームを配置
            grid_image[y_start:y_end, x_start:x_end] = resized_frame

            # connection_id をラベルとして表示
            cv2.putText(
                grid_image,
                connection_id,
                (x_start + 5, y_start + 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )

        return grid_image

    def _callback(
        self, outdata: ndarray, frames: int, time: Any, status: sounddevice.CallbackFlags
    ) -> None:
        if self._audio_sink is not None:
            success, data = self._audio_sink.read(frames)
            if success:
                if data.shape[0] != frames:
                    print("Audio data is insufficient: ", data.shape, frames)
                outdata[:] = data
            else:
                print("Unable to obtain audio data")

    def run(self) -> None:
        # 音声出力ストリームを開始
        with sounddevice.OutputStream(
            channels=self._output_channels,
            callback=self._callback,
            samplerate=self._output_frequency,
            dtype="int16",
        ):
            self.connect()
            try:
                while self._connected.is_set():
                    # フレーム辞書と順序のコピーを取得
                    with self._video_frames_lock:
                        frames_snapshot = self._video_frames.copy()
                        connection_order_snapshot = self._connection_order.copy()

                    # グリッド画像を生成して表示
                    if frames_snapshot:
                        grid_image = self._create_grid_image(
                            frames_snapshot, connection_order_snapshot
                        )
                        if grid_image is not None:
                            cv2.imshow("Sora Recvonly - Grid View", grid_image)

                    # 'q' キーで終了
                    if cv2.waitKey(30) & 0xFF == ord("q"):
                        break
            except KeyboardInterrupt:
                pass
            finally:
                self.disconnect()
                cv2.destroyAllWindows()


def _parse_args(argv: list[str] | None = None):
    parser = EnvPrefixArgumentParser(
        env_prefix="SORA_",
        description="Sora recvonly sample application for receiving video and audio streams",
    )
    parser.add_argument(
        "--signaling-url",
        dest="signaling_urls",
        nargs="+",
        metavar="URL",
        help="Sora signaling URL(s). Multiple URLs can be specified for redundancy (e.g., --signaling-url wss://example.com/signaling --signaling-url wss://backup.com/signaling)",
    )
    parser.add_argument(
        "--channel-id",
        dest="channel_id",
        help="Sora channel ID to connect to. This identifies the communication channel where video and audio streams are exchanged",
    )
    parser.add_argument(
        "--channel-id-prefix",
        dest="channel_id_prefix",
        help="Prefix used to generate a unique channel ID. If specified, a random suffix will be appended to create the full channel ID",
    )
    parser.add_argument(
        "--metadata",
        dest="metadata",
        type=json_object,
        help='JSON metadata to send when connecting to Sora. Must be valid JSON format (e.g., \'{"key": "value"}\')',
    )
    parser.add_argument(
        "--output-frequency",
        dest="output_frequency",
        type=int,
        default=16000,
        help="Audio output sampling frequency in Hz. Default is 16000 Hz. Common values are 8000, 16000, 24000, or 48000",
    )
    parser.add_argument(
        "--output-channels",
        dest="output_channels",
        type=int,
        default=1,
        help="Number of audio output channels. Default is 1 (mono). Set to 2 for stereo output",
    )
    parser.add_argument(
        "--data-channel-signaling",
        dest="data_channel_signaling",
        action="store_true",
        default=None,
        help="Enable data channel signaling instead of WebSocket signaling. When enabled, signaling messages are sent over WebRTC data channels after initial connection",
    )
    parser.add_argument(
        "--openh264-path",
        dest="openh264_path",
        help="Path to the OpenH264 library file for H.264 video decoding. Required when receiving H.264 encoded video streams",
    )
    parser.add_argument(
        "--grid-cols",
        dest="grid_cols",
        type=int,
        default=3,
        help="Number of columns in the grid layout for displaying multiple video streams. Default is 3. Videos will wrap to the next row when this limit is reached",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    signaling_urls = args.signaling_urls
    if not signaling_urls:
        raise ValueError("シグナリング URL が指定されていません")

    channel_id = resolve_channel_id(args.channel_id, args.channel_id_prefix)

    if args.output_frequency is None:
        raise ValueError("音声出力周波数を整数で指定してください")

    if args.output_channels is None:
        raise ValueError("音声出力チャンネル数を整数で指定してください")

    video_codec_preference = get_video_codec_preference(args.openh264_path)

    recvonly_instance = Recvonly(
        signaling_urls,
        channel_id,
        metadata=args.metadata,
        data_channel_signaling=args.data_channel_signaling,
        openh264_path=args.openh264_path,
        video_codec_preference=video_codec_preference,
        output_frequency=args.output_frequency,
        output_channels=args.output_channels,
        grid_cols=args.grid_cols,
    )
    recvonly_instance.run()


if __name__ == "__main__":
    main()
