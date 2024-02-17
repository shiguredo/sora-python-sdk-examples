import argparse
import json
import os
import queue
from threading import Event
from typing import List

import cv2
import sounddevice
from sora_sdk import Sora, SoraAudioSink, SoraConnection, SoraVideoSink


class Recvonly:
    _sora: Sora
    _connection: SoraConnection

    _connection_id: str

    _connected: Event
    _closed: bool = False

    _audio_sink: SoraAudioSink
    _video_sink: SoraVideoSink

    def __init__(
        self,
        # python 3.8 まで対応なので list[str] ではなく List[str] にする
        signaling_urls: List[str],
        channel_id,
        metadata,
        openh264,
        output_frequency=16000,
        output_channels=1,
    ):
        self.output_frequency = output_frequency
        self.output_channels = output_channels

        self._sora = Sora(openh264=openh264)
        self._connection = self._sora.create_connection(
            signaling_urls=signaling_urls,
            role="recvonly",
            channel_id=channel_id,
            metadata=metadata,
        )

        self._connection.on_disconnect = self.on_disconnect

        self.q_out = queue.Queue()

        self._connection.on_track = self.on_track

    def connect(self):
        self._connection.connect()

        assert self._connected.wait(timeout=10), "接続に失敗しました"

    def disconnect(self):
        self._connection.disconnect()

    def _on_set_offer(self, raw_message: str):
        message = json.loads(raw_message)
        if message["type"] == "offer":
            self._connection_id = message["connection_id"]

    def _on_notify(self, raw_message: str):
        message = json.loads(raw_message)
        if (
            message["type"] == "notify"
            and message["event"] == "connection.created"
            and message["connection_id"] == self._connection_id
        ):
            self._connected.set()

    def on_disconnect(self, error_code, message):
        print(f"Sora から切断されました: error_code='{error_code}' message='{message}'")
        self._closed = True
        self._connected.clear()

    def on_frame(self, frame):
        self.q_out.put(frame)

    def on_track(self, track):
        if track.kind == "audio":
            self._audio_sink = SoraAudioSink(track, self.output_frequency, self.output_channels)
        if track.kind == "video":
            self._video_sink = SoraVideoSink(track)
            self._video_sink.on_frame = self.on_frame

    def callback(self, outdata, frames, time, status):
        if self.audio_sink is not None:
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
            channels=self.output_channels,
            callback=self.callback,
            samplerate=self.output_frequency,
            dtype="int16",
        ):
            self.connect()

            try:
                while not self._closed:
                    # Windows 環境の場合 timeout を入れておかないと Queue.get() で
                    # ブロックしたときに脱出方法がなくなる。
                    try:
                        frame = self.q_out.get(timeout=1)
                    except queue.Empty:
                        continue
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
    parser.add_argument("--metadata", default=os.getenv("SORA_METADATA"), help="メタデータ JSON")
    parser.add_argument(
        "--openh264", type=str, default=None, help="OpenH264 の共有ライブラリへのパス"
    )
    args = parser.parse_args()

    metadata = {}
    if args.metadata:
        metadata = json.loads(args.metadata)

    recvonly = Recvonly(args.signaling_urls, args.channel_id, metadata, args.openh264)
    recvonly.run()


if __name__ == "__main__":
    recvonly()
