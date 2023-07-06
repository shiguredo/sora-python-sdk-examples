import argparse
import json
import os
import queue

import cv2
import sounddevice
from sora_sdk import Sora, SoraAudioSink, SoraVideoSink


class Recvonly:
    def __init__(self, signaling_urls, channel_id,
                 metadata, openh264, output_frequency=16000, output_channels=1):
        self.output_frequency = output_frequency
        self.output_channels = output_channels

        self.sora = Sora(openh264=openh264)
        self.connection = self.sora.create_connection(
            signaling_urls=signaling_urls,
            role="recvonly",
            channel_id=channel_id,
            metadata=metadata
        )

        self.shutdown = False
        self.connection.on_disconnect = self.on_disconnect

        self.audio_sink = None
        self.video_sink = None
        self.q_out = queue.Queue()

        self.connection.on_track = self.on_track

    def on_disconnect(self, error_code, message):
        print(f"Sora から切断されました: error_code='{error_code}' message='{message}'")
        self.shutdown = True

    def on_frame(self, frame):
        self.q_out.put(frame)

    def on_track(self, track):
        if track.kind == "audio":
            self.audio_sink = SoraAudioSink(
                track, self.output_frequency, self.output_channels)
        if track.kind == "video":
            self.video_sink = SoraVideoSink(track)
            self.video_sink.on_frame = self.on_frame

    def callback(self, outdata, frames, time, status):
        if self.audio_sink is not None:
            success, data = self.audio_sink.read(frames)
            if success:
                if data.shape[0] != frames:
                    print("音声データが十分ではありません", data.shape, frames)
                outdata[:] = data
            else:
                print("音声データを取得できません")

    def run(self):
        # サウンドデバイスのOutputStreamを使って音声出力を設定
        with sounddevice.OutputStream(channels=self.output_channels, callback=self.callback,
                                      samplerate=self.output_frequency, dtype='int16'):
            self.connection.connect()

            try:
                while not self.shutdown:
                    # Windows 環境の場合 timeout を入れておかないと Queue.get() で
                    # ブロックしたときに脱出方法がなくなる。
                    try:
                        frame = self.q_out.get(timeout=1)
                    except queue.Empty:
                        continue
                    cv2.imshow('frame', frame.data())
                    # これは削除してよさそう
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
            except KeyboardInterrupt:
                pass
            finally:
                self.connection.disconnect()

                # すべてのウィンドウを破棄
                cv2.destroyAllWindows()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    # オプション引数の代わりに環境変数による指定も可能。
    # 必須引数
    default_signaling_urls = os.getenv("SORA_SIGNALING_URLS")
    parser.add_argument("--signaling-urls", default=default_signaling_urls,
                        type=str, nargs='+',
                        required=not default_signaling_urls, help="シグナリング URL")
    default_channel_id = os.getenv("SORA_CHANNEL_ID")
    parser.add_argument("--channel-id", default=default_channel_id,
                        required=not default_channel_id, help="チャネルID")

    # オプション引数
    parser.add_argument(
        "--metadata", default=os.getenv("SORA_METADATA"), help="メタデータ JSON")
    parser.add_argument("--openh264", type=str, default=None,
                        help="OpenH264 の共有ライブラリへのパス")
    args = parser.parse_args()

    metadata = {}
    if args.metadata:
        metadata = json.loads(args.metadata)

    recvonly = Recvonly(args.signaling_urls, args.channel_id, metadata, args.openh264)
    recvonly.run()
