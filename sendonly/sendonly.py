import argparse
import json
import os

import cv2
import sounddevice
from sora_sdk import Sora


class SendOnly:
    def __init__(
        self,
        signaling_urls,
        channel_id,
        metadata,
        camera_id,
        audio_codec_type,
        video_codec_type,
        video_bit_rate,
        video_width,
        video_height,
        openh264,
        channels=1,
        samplerate=16000,
    ):
        self.running = True
        self.channels = channels
        self.samplerate = samplerate

        self.sora = Sora(openh264=openh264)
        self.audio_source = self.sora.create_audio_source(self.channels, self.samplerate)
        self.video_source = self.sora.create_video_source()
        self.connection = self.sora.create_connection(
            signaling_urls=signaling_urls,
            role="sendonly",
            channel_id=channel_id,
            metadata=metadata,
            audio_codec_type=audio_codec_type,
            video_codec_type=video_codec_type,
            video_bit_rate=video_bit_rate,
            audio_source=self.audio_source,
            video_source=self.video_source,
        )
        self.connection.on_disconnect = self.on_disconnect

        self.video_capture = cv2.VideoCapture(camera_id)
        if video_width is not None:
            self.video_capture.set(cv2.CAP_PROP_FRAME_WIDTH, video_width)
        if video_height is not None:
            self.video_capture.set(cv2.CAP_PROP_FRAME_HEIGHT, video_height)

    def on_disconnect(self, error_code, message):
        print(f"Sora から切断されました: error_code='{error_code}' message='{message}'")
        self.running = False

    def callback(self, indata, frames, time, status):
        self.audio_source.on_data(indata)

    def run(self):
        with sounddevice.InputStream(
            samplerate=self.samplerate,
            channels=self.channels,
            dtype="int16",
            callback=self.callback,
        ):
            self.connection.connect()

            try:
                while self.running:
                    success, frame = self.video_capture.read()
                    if not success:
                        continue
                    self.video_source.on_captured(frame)
            except KeyboardInterrupt:
                pass
            finally:
                self.connection.disconnect()
                self.video_capture.release()


if __name__ == "__main__":
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
    parser.add_argument(
        "--audio-codec-type",
        default=os.getenv("SORA_AUDIO_CODEC_TYPE"),
        help="音声コーデックの種類",
    )
    parser.add_argument(
        "--video-codec-type",
        default=os.getenv("SORA_VIDEO_CODEC_TYPE"),
        help="映像コーデックの種類",
    )
    parser.add_argument(
        "--video-bit-rate",
        type=int,
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
        default=os.getenv("SORA_VIDEO_WIDTH"),
        help="入力カメラ映像の横幅のヒント",
    )
    parser.add_argument(
        "--video-height",
        type=int,
        default=os.getenv("SORA_VIDEO_HEIGHT"),
        help="入力カメラ映像の高さのヒント",
    )
    parser.add_argument(
        "--openh264", type=str, default=None, help="OpenH264 の共有ライブラリへのパス"
    )
    args = parser.parse_args()

    metadata = {}
    if args.metadata:
        metadata = json.loads(args.metadata)

    sendonly = SendOnly(
        args.signaling_urls,
        args.channel_id,
        metadata,
        args.camera_id,
        args.audio_codec_type,
        args.video_codec_type,
        args.video_bit_rate,
        args.video_width,
        args.video_height,
        args.openh264,
    )
    sendonly.run()
