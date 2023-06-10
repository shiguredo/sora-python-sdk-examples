import argparse
import json
import os
import signal

import cv2
import sounddevice

from sora_sdk import Sora


class SendOnly:
    def __init__(self, signaling_url, channel_id, client_id, metadata, camera_id,
                 use_hardware_encoder=False, channels=1, samplerate=16000):
        self.running = True
        self.channels = channels
        self.samplerate = samplerate
        self.use_hardware_encoder = use_hardware_encoder

        self.sora = Sora(self.use_hardware_encoder)
        self.audio_source = self.sora.create_audio_source(
            self.channels, self.samplerate)
        self.video_source = self.sora.create_video_source()
        self.connection = self.sora.create_connection(
            signaling_url=signaling_url,
            role="sendonly",
            channel_id=channel_id,
            client_id=client_id,
            metadata=metadata,
            audio_source=self.audio_source,
            video_source=self.video_source
        )
        self.connection.on_disconnect = self.on_disconnect

        self.video_capture = cv2.VideoCapture(camera_id)

    def on_disconnect(self, ec, message):
        self.running = False

    def handler(self, signum, frame):
        self.running = False

    def callback(self, indata, frames, time, status):
        self.audio_source.on_data(indata)

    def run(self):
        signal.signal(signal.SIGINT, self.handler)

        with sounddevice.InputStream(samplerate=self.samplerate, channels=self.channels,
                                     dtype='int16', callback=self.callback):
            self.connection.connect()

            try:
                while self.running:
                    success, frame = self.video_capture.read()
                    if not success:
                        continue
                    self.video_source.on_captured(frame)
            finally:
                self.connection.disconnect()
                self.video_capture.release()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    # 必須引数
    signaling_url = os.getenv("SIGNALING_URL")
    parser.add_argument("--signaling-url", default=signaling_url, required=not signaling_url, help="シグナリング URL")
    channel_id = os.getenv("CHANNEL_ID")
    parser.add_argument("--channel-id", default=channel_id, required=not channel_id, help="チャネルID")

    # オプション引数
    parser.add_argument("--client-id", default=os.getenv("CLIENT_ID", ""),  help="クライアントID")
    parser.add_argument("--metadata", default=os.getenv("METADATA"), help="メタデータ JSON")
    parser.add_argument("--camera-id", type=int, default=int(os.getenv("CAMERA_ID", "0")), help="cv2.VideoCapture() に渡すカメラ ID")
    args = parser.parse_args()

    metadata = None
    if args.metadata:
        metadata = json.loads(args.metadata)

    sendonly = SendOnly(args.signaling_url, args.channel_id,
                        args.client_id, metadata, args.camera_id)
    sendonly.run()
