import argparse
import json
import math
import os
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from PIL import Image
from sora_sdk import Sora


class LogoStreamer:
    def __init__(self, signaling_urls, role, channel_id, metadata, camera_id,
                 video_width, video_height):
        self.mp_face_detection = mp.solutions.face_detection

        self.sora = Sora()
        self.video_source = self.sora.create_video_source()
        self.connection = self.sora.create_connection(
            signaling_urls=signaling_urls,
            role=role,
            channel_id=channel_id,
            metadata=metadata,
            video_source=self.video_source,
        )
        self.connection.on_disconnect = self.on_disconnect

        self.video_capture = cv2.VideoCapture(camera_id)
        if video_width is not None:
            self.video_capture.set(cv2.CAP_PROP_FRAME_WIDTH, video_width)
        if video_height is not None:
            self.video_capture.set(cv2.CAP_PROP_FRAME_HEIGHT, video_height)

        self.running = True
        # ロゴを読み込む
        self.logo = Image.open(
            Path(__file__).parent.joinpath("shiguremaru.png"))

    def on_disconnect(self, error_code, message):
        print(f"Sora から切断されました: error_code='{error_code}' message='{message}'")
        self.running = False

    def run(self):
        self.connection.connect()
        try:
            # 顔検出を用意する
            with self.mp_face_detection.FaceDetection(
                    model_selection=0, min_detection_confidence=0.5
            ) as face_detection:
                angle = 0
                while self.running and self.video_capture.isOpened():
                    angle = self.run_one_frame(face_detection, angle)
        except KeyboardInterrupt:
            pass
        finally:
            self.connection.disconnect()
            self.video_capture.release()

    def run_one_frame(self, face_detection, angle):
        while self.running and self.video_capture.isOpened():
            # フレームを取得する
            success, frame = self.video_capture.read()
            if not success:
                continue

            # 高速化の呪文
            frame.flags.writeable = False
            # mediapipe や PIL で処理できるように色の順序を変える
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            # mediapipe で顔を検出する
            results = face_detection.process(frame)

            frame_height, frame_width, _ = frame.shape
            # PIL で処理できるように画像を変換する
            pil_image = Image.fromarray(frame)

            # ロゴを回しておく
            rotated_logo = self.logo.rotate(angle)
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
                    x_px = min(math.floor(
                        bb.xmin * frame_width), frame_width - 1)
                    y_px = min(math.floor(
                        bb.ymin * frame_height), frame_height - 1)

                    # 検出領域は顔に対して小さいため、顔全体が覆われるように検出領域を大きくする
                    fixed_w_px = math.floor(w_px * 1.6)
                    fixed_h_px = math.floor(h_px * 1.6)
                    # 大きくした分、座標がずれてしまうため顔の中心になるように座標を補正する
                    fixed_x_px = max(0, math.floor(
                        x_px - (fixed_w_px - w_px) / 2))
                    # 検出領域は顔であり頭が入っていないため、上寄りになるように座標を補正する
                    fixed_y_px = max(0, math.floor(
                        y_px - (fixed_h_px - h_px)))

                    # ロゴをリサイズする
                    resized_logo = rotated_logo.resize(
                        (fixed_w_px, fixed_h_px))
                    pil_image.paste(
                        resized_logo, (fixed_x_px,
                                       fixed_y_px), resized_logo
                    )

            frame.flags.writeable = True
            # PIL から numpy に画像を戻す
            frame = np.array(pil_image)
            # 色の順序をもとに戻す
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

            # WebRTC に渡す
            self.video_source.on_captured(frame)

        return angle


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    # 必須引数
    default_signaling_urls = os.getenv("SORA_SIGNALING_URLS")
    parser.add_argument("--signaling-urls", default=default_signaling_urls,
                        type=str, nargs='+',
                        required=not default_signaling_urls, help="シグナリング URL")
    default_channel_id = os.getenv("SORA_CHANNEL_ID")
    parser.add_argument("--channel-id", default=default_channel_id,
                        required=not default_channel_id, help="チャネルID")

    # オプション引数
    parser.add_argument("--metadata", help="メタデータ JSON")
    parser.add_argument("--camera-id", type=int, default=0,
                        help="cv2.VideoCapture() に渡すカメラ ID")
    parser.add_argument("--video-width", type=int, default=os.getenv("SORA_VIDEO_WIDTH"),
                        help="入力カメラ映像の横幅のヒント")
    parser.add_argument("--video-height", type=int, default=os.getenv("SORA_VIDEO_HEIGHT"),
                        help="入力カメラ映像の高さのヒント")
    args = parser.parse_args()

    metadata = None
    if args.metadata:
        metadata = json.loads(args.metadata)

    streamer = LogoStreamer(
        signaling_urls=args.signaling_urls,
        role="sendonly",
        channel_id=args.channel_id,
        metadata=args.metadata,
        camera_id=args.camera_id,
    )
    streamer.run()
