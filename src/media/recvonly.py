import argparse
import json
import os
import queue
from threading import Event
from typing import Any, Dict, List, Optional

import cv2
import sounddevice
from dotenv import load_dotenv
from numpy import ndarray
from sora_sdk import (
    Sora,
    SoraAudioSink,
    SoraConnection,
    SoraMediaTrack,
    SoraSignalingErrorCode,
    SoraVideoFrame,
    SoraVideoSink,
)


class Recvonly:
    def __init__(
        self,
        # python 3.8 まで対応なので list[str] ではなく List[str] にする
        signaling_urls: List[str],
        channel_id: str,
        metadata: Optional[Dict[str, Any]],
        openh264: Optional[str],
        output_frequency: int = 16000,
        output_channels: int = 1,
    ):
        self._output_frequency = output_frequency
        self._output_channels = output_channels

        self._sora: Sora = Sora(openh264=openh264)
        self._connection: SoraConnection = self._sora.create_connection(
            signaling_urls=signaling_urls,
            role="recvonly",
            channel_id=channel_id,
            metadata=metadata,
        )
        self._connection_id = ""
        self._connected = Event()
        self._closed = False
        self._default_connection_timeout_s = 10.0

        self._audio_sink: Optional[SoraAudioSink] = None
        self._video_sink: Optional[SoraVideoSink] = None

        # SoraVideoFrame を格納するキュー
        self._q_out: queue.Queue = queue.Queue()

        self._connection.on_set_offer = self._on_set_offer
        self._connection.on_notify = self._on_notify
        self._connection.on_disconnect = self._on_disconnect
        self._connection.on_track = self._on_track

    def connect(self):
        self._connection.connect()

        assert self._connected.wait(
            timeout=self._default_connection_timeout_s
        ), "接続に失敗しました"

    def disconnect(self):
        self._connection.disconnect()

    def _on_set_offer(self, raw_message: str):
        message: Dict[str, Any] = json.loads(raw_message)
        if message["type"] == "offer":
            # "type": "offer" に入ってくる自分の connection_id を保存する
            self._connection_id = message["connection_id"]

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

    def _on_disconnect(self, error_code: SoraSignalingErrorCode, message: str):
        print(f"Sora から切断されました: error_code='{error_code}' message='{message}'")
        self._connected.clear()
        self._closed = True

    def _on_video_frame(self, frame: SoraVideoFrame):
        # キューに SoraVideoFrame を入れる
        self._q_out.put(frame)

    def _on_track(self, track: SoraMediaTrack):
        if track.kind == "audio":
            self._audio_sink = SoraAudioSink(track, self._output_frequency, self._output_channels)
        if track.kind == "video":
            self._video_sink = SoraVideoSink(track)
            self._video_sink.on_frame = self._on_video_frame

    def _callback(self, outdata: ndarray, frames: int, time, status: sounddevice.CallbackFlags):
        if self._audio_sink is not None:
            success, data = self._audio_sink.read(frames)
            if success:
                if data.shape[0] != frames:
                    print("音声データが十分ではありません", data.shape, frames)
                outdata[:] = data
            else:
                print("音声データを取得できません")

    def run(self):
        # サウンドデバイスのOutputStreamを使って音声出力を設定
        with sounddevice.OutputStream(
            channels=self._output_channels,
            callback=self._callback,
            samplerate=self._output_frequency,
            dtype="int16",
        ):
            self.connect()
            try:
                while self._connected.is_set():
                    # Windows 環境の場合 timeout を入れておかないと Queue.get() で
                    # ブロックしたときに脱出方法がなくなる。
                    try:
                        # キューから SoraVideoFrame を取り出す
                        frame = self._q_out.get(timeout=1)
                    except queue.Empty:
                        continue
                    # 画像を表示する
                    cv2.imshow("frame", frame.data())
                    # これは削除してよさそう
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
            except KeyboardInterrupt:
                pass
            finally:
                self.disconnect()

                # すべてのウィンドウを破棄
                cv2.destroyAllWindows()


def recvonly():
    # .env ファイル読み込み
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
    parser.add_argument("--metadata", default=os.getenv("SORA_METADATA"), help="メタデータ JSON")
    parser.add_argument(
        "--openh264", type=str, default=None, help="OpenH264 の共有ライブラリへのパス"
    )
    args = parser.parse_args()

    metadata = None
    if args.metadata:
        metadata = json.loads(args.metadata)

    recvonly = Recvonly(args.signaling_urls, args.channel_id, metadata, args.openh264)
    recvonly.run()


if __name__ == "__main__":
    recvonly()
