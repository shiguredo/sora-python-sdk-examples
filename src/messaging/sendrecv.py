# Sora のデータチャネル機能を使ってメッセージを送受信するサンプルスクリプト。
#
# コマンドライン引数で指定されたデータチャネル JSON (e.g, `[{"label": "#foo", "direction": "recvonly"}, {"label": "#bar", "direction": "sendonly"}]`) に従って、メッセージの送信および受信を行う。
#
# 具体的には、
# - `direction` が `recvonly` または `sendrecv` のデータチャネルに対して、メッセージを受信したら標準出力に出力する
# - `direction` が `sendonly` または `sendrecv` のデータチャネルに対して、1 秒ごとに自動生成したメッセージを送信する
#
# 実行例:
# $ rye run python src/messaging_sendrecv.py --signaling-urls wss://sora.example.com/signaling --channel-id sora --data-channels '[{"label": "#foo", "direction":"sendrecv"}, {"label":"#bar", "direction": "recvonly"}]'
import argparse
import json
import os
import random
import time
from threading import Event
from typing import Any, Dict, List

from sora_sdk import Sora, SoraConnection, SoraSignalingErrorCode


class MessagingSendrecv:
    _sora: Sora
    _connection: SoraConnection

    _connection_id: str

    _connected: Event
    _closed: bool = False

    _data_channels: [Dict[str, Any]]
    _sendable_data_channels: set = set()

    def __init__(
        self,
        # python 3.8 まで対応なので list[str] ではなく List[str] にする
        signaling_urls: List[str],
        channel_id: str,
        data_channels: [Dict[str, Any]],
        metadata: Dict[str, Any],
    ):
        self._sora = Sora()
        self._connection = self._sora.create_connection(
            signaling_urls=signaling_urls,
            role="sendrecv",
            channel_id=channel_id,
            metadata=metadata,
            audio=False,
            video=False,
            data_channels=data_channels,
            data_channel_signaling=True,
        )

        self.sender_id = random.randint(1, 10000)

        self._data_channels = data_channels

        self._connection.on_data_channel = self._on_data_channel
        self._connection.on_message = self._on_message
        self._connection.on_disconnect = self._on_disconnect

    def connect(self):
        self._connection.connect()

        assert self._connected.wait(10), "接続に失敗しました"

    def disconnect(self):
        self._connection.disconnect()

    def _on_set_offer(self, raw_message: str):
        message = json.loads(raw_message)
        if message["type"] == "offer":
            self._connection_id = message["connectionId"]
            self._connected.set()

    def _on_notify(self, raw_message: str):
        message = json.loads(raw_message)
        if (
            message["type"] == "notify"
            and message["event"] == "connection.created"
            and message["connectionId"] == self._connection_id
        ):
            self._connected.set()

    def _on_disconnect(self, error_code: SoraSignalingErrorCode, message: str):
        print(f"Sora から切断されました: error_code='{error_code}' message='{message}'")
        self._closed = True
        self._connected.clear()

    def _on_message(self, label: str, data: bytes):
        print(f"メッセージを受信しました: label={label}, data={data}")

    def _on_data_channel(self, label: str):
        for data_channel in self._data_channels:
            if data_channel["label"] != label:
                continue

            if data_channel["direction"] in ["sendrecv", "sendonly"]:
                self._sendable_data_channels.add(label)
                break

    def run(self):
        # Sora に接続する
        self.connect()
        try:
            # 一秒毎に sendonly ないし sendrecv のラベルにメッセージを送信する
            i = 0
            while not self._closed:
                if i % 100 == 0:
                    for label in self._sendable_data_channels:
                        data = f"sender={self.sender_id}, no={i // 100}".encode("utf-8")
                        self._connection.send_data_channel(label, data)
                        print(f"メッセージを送信しました: label={label}, data={data}")

                time.sleep(0.01)
                i += 1
        except KeyboardInterrupt:
            pass
        finally:
            # Sora から切断する（すでに切断済みの場合には無視される）
            self.disconnect()


def main():
    parser = argparse.ArgumentParser()

    # 必須引数（環境変数からも指定可能）
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
    default_ddata_channels = os.getenv("SORA_DATA_CHANNELS")
    parser.add_argument(
        "--data-channels",
        default=default_ddata_channels,
        required=not default_ddata_channels,
        help='使用するデータチャネルを JSON で指定する (例: \'[{"label": "#spam", "direction": "sendrecv"}]\')',
    )

    # オプション引数
    parser.add_argument("--metadata", default=os.getenv("SORA_METADATA"), help="メタデータ JSON")
    args = parser.parse_args()

    metadata = None
    if args.metadata:
        metadata = json.loads(args.metadata)

    messaging_sendrecv = MessagingSendrecv(
        args.signaling_urls, args.channel_id, json.loads(args.data_channels), metadata
    )
    messaging_sendrecv.run()


if __name__ == "__main__":
    main()
