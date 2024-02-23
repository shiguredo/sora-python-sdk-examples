# Sora のデータチャネル機能を使ってメッセージを受信するサンプルスクリプト。
#
# コマンドライン引数で指定されたチャネルおよびラベルに届いたメッセージを標準出力に表示する。
#
# 実行例:
# $ rye run python src/messaging_recvonly.py --signaling-urls wss://example.com/signaling --channel-id sora --labels '#foo' '#bar'
import argparse
import json
import os
import time
from threading import Event
from typing import Dict, List

from sora_sdk import Sora, SoraConnection


class MessagingRecvonly:
    def __init__(
        self,
        signaling_urls: List[str],
        channel_id: str,
        labels: List[str],
        metadata: Dict[str, str],
    ):
        self._sora = Sora()
        self._connection: SoraConnection = self._sora.create_connection(
            signaling_urls=signaling_urls,
            role="sendrecv",
            channel_id=channel_id,
            metadata=metadata,
            audio=False,
            video=False,
            data_channels=[{"label": label, "direction": "recvonly"} for label in labels],
            data_channel_signaling=True,
        )

        self._connection_id = str("")
        self._connected = Event()
        self._closed = False

        self._connection.on_set_offer = self._on_set_offer
        self._connection.on_notify = self._on_notify
        self._connection.on_message = self._on_message
        self._connection.on_disconnect = self._on_disconnect

    def connect(self):
        self._connection.connect()

        # XXX: マジックナンバーを使っているので修正する
        assert self._connected.wait(timeout=10), "接続がタイムアウトしました"

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
            and message["event_type"] == "connection.created"
            and message["connection_id"] == self._connection_id
        ):
            self._connected.set()

    def on_disconnect(self, error_code, message):
        print(f"Sora から切断されました: error_code='{error_code}' message='{message}'")
        self._closed = True
        self._connected.clear()

    def _on_message(self, label, data):
        print(f"メッセージを受信しました: label={label}, data={data}")

    def run(self):
        # Sora に接続する
        self.connect()
        try:
            # Ctrl+C が押される or 切断されるまでメッセージ受信を待機
            while not self.shutdown:
                time.sleep(0.01)
        except KeyboardInterrupt:
            pass
        finally:
            # Sora から切断する（すでに切断済みの場合には無視される）
            self.disconnect()


def recvonly():
    parser = argparse.ArgumentParser()

    # 必須引数（環境変数からも指定可能）
    # SORA_SIGNALING_URLS 環境変数はカンマ区切りで複数指定可能
    if urls := os.getenv("SORA_SIGNALING_URLS"):
        default_signaling_urls = urls.split(",")
    else:
        default_signaling_urls = None
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
    if labels := os.getenv("SORA_RECVONLY_LABEL"):
        default_labels = labels.split(",")
    else:
        default_labels = None
    parser.add_argument(
        "--labels",
        default=default_labels,
        required=not labels,
        nargs="+",
        help="受信するデータチャネルのラベル名（複数指定可能）",
    )

    # オプション引数
    parser.add_argument("--metadata", default=os.getenv("SORA_METADATA"), help="メタデータ JSON")
    args = parser.parse_args()

    metadata: Dict[str, str] = {}
    if args.metadata:
        metadata = json.loads(args.metadata)

    messaging_recvonly = MessagingRecvonly(
        args.signaling_urls, args.channel_id, args.labels, metadata
    )
    messaging_recvonly.run()


if __name__ == "__main__":
    recvonly()
