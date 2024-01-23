# Sora のデータチャネル機能を使ってメッセージを送信するサンプルスクリプト。
#
# コマンドライン引数で指定されたチャネルおよびラベルに、同じくコマンドライン引数で指定されたデータを送信する。
#
# 実行例:
# $ rye run python messaging_sendonly/messaging_sendonly.py --signaling-urls wss://sora.example.com/signaling --channel-id sora --label '#foo' --data hello
import argparse
import json
import os
import time

from sora_sdk import Sora


class MessagingSendonly:
    def __init__(self, signaling_urls, channel_id, label, metadata):
        self.sora = Sora()
        self.connection = self.sora.create_connection(
            signaling_urls=signaling_urls,
            role="sendrecv",
            channel_id=channel_id,
            metadata=metadata,
            audio=False,
            video=False,
            data_channels=[{"label": label, "direction": "sendonly"}],
            data_channel_signaling=True,
        )

        self.disconnected = False
        self.label = label
        self.is_data_channel_ready = False
        self.connection.on_data_channel = self.on_data_channel
        self.connection.on_disconnect = self.on_disconnect

    def on_disconnect(self, error_code, message):
        print(f"Sora から切断されました: error_code='{error_code}' message='{message}'")
        self.disconnected = True

    def on_data_channel(self, label):
        if self.label == label:
            self.is_data_channel_ready = True

    def connect(self):
        self.connection.connect()

    def send(self, data):
        # on_data_channel() が呼ばれるまではデータチャネルの準備ができていないので待機
        while not self.is_data_channel_ready and not self.disconnected:
            time.sleep(0.01)

        self.connection.send_data_channel(self.label, data)
        print(f"メッセージを送信しました: label={self.label}, data={data}")

    def disconnect(self):
        self.connection.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    # 必須引数
    default_signaling_urls = os.getenv("SORA_SIGNALING_URLS")
    parser.add_argument(
        "--signaling-urls",
        default=default_signaling_urls,
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
    default_sendonly_label = os.getenv("SORA_SENDONLY_LABEL")
    parser.add_argument(
        "--label",
        default=default_sendonly_label,
        required=not default_sendonly_label,
        help="送信するデータチャネルのラベル名",
    )
    default_sendonly_data = os.getenv("SORA_SENDONLY_DATA")
    parser.add_argument(
        "--data",
        default=default_sendonly_data,
        required=not default_sendonly_data,
        help="送信するデータ",
    )

    # オプション引数
    parser.add_argument("--metadata", default=os.getenv("SORA_METADATA"), help="メタデータ JSON")
    args = parser.parse_args()

    metadata = None
    if args.metadata:
        metadata = json.loads(args.metadata)

    messaging_sendonly = MessagingSendonly(
        args.signaling_urls, args.channel_id, args.label, metadata
    )
    messaging_sendonly.connect()
    messaging_sendonly.send(args.data.encode("utf-8"))
    messaging_sendonly.disconnect()
