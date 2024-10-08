import json
import os
import random
import time
from threading import Event
from typing import Any, Optional

from dotenv import load_dotenv
from sora_sdk import Sora, SoraConnection, SoraSignalingErrorCode


class Messaging:
    """Sora を使用してメッセージングを行うクラス。"""

    def __init__(
        self,
        signaling_urls: list[str],
        channel_id: str,
        data_channels: list[dict[str, Any]],
        metadata: Optional[dict[str, Any]] = None,
    ):
        """
        Messaging インスタンスを初期化します。

        このクラスは Sora への接続を設定し、データチャネルを通じてメッセージの
        送受信を行うメソッドを提供します。

        :param signaling_urls: Sora シグナリング URL のリスト
        :param channel_id: 接続するチャンネル ID
        :param data_channels: データチャネルの設定リスト
        :param metadata: 接続のためのオプションのメタデータ
        """
        self._data_channels = data_channels

        self._sora = Sora()
        self._connection: SoraConnection = self._sora.create_connection(
            signaling_urls=signaling_urls,
            role="sendrecv",
            channel_id=channel_id,
            metadata=metadata,
            audio=False,
            video=False,
            data_channels=self._data_channels,
            data_channel_signaling=True,
        )
        self._connection_id: Optional[str] = None

        self._connected = Event()
        self._switched: bool = False
        self._closed = Event()
        self._default_connection_timeout_s: float = 10.0

        self._label = data_channels[0]["label"]
        self._sendable_data_channels: set = set()
        self._is_data_channel_ready = False

        self.sender_id = random.randint(1, 10000)

        self._connection.on_set_offer = self._on_set_offer
        self._connection.on_switched = self._on_switched
        self._connection.on_notify = self._on_notify
        self._connection.on_data_channel = self._on_data_channel
        self._connection.on_message = self._on_message
        self._connection.on_disconnect = self._on_disconnect

    @property
    def closed(self):
        """接続が閉じられているかどうかを示すブール値。"""
        return self._closed.is_set()

    def connect(self):
        """
        Sora への接続を確立します。

        :raises AssertionError: タイムアウト期間内に接続が確立できなかった場合
        """
        self._connection.connect()

        assert self._connected.wait(
            self._default_connection_timeout_s
        ), "Could not connect to Sora."

    def disconnect(self):
        """Sora から切断します。"""
        self._connection.disconnect()

    def get_stats(self):
        raw_stats = self._connection.get_stats()
        stats = json.loads(raw_stats)
        return stats

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    @property
    def switched(self) -> bool:
        return self._switched

    def send(self, data: bytes):
        """
        データチャネルを通じてメッセージを送信します。

        :param data: 送信するバイトデータ
        """
        # on_data_channel() が呼ばれるまではデータチャネルの準備ができていないので待機
        while not self._is_data_channel_ready and not self._closed.is_set():
            time.sleep(0.01)

        self._connection.send_data_channel(self._label, data)

    def _on_set_offer(self, raw_message: str):
        """
        オファー設定イベントを処理します。

        :param raw_message: オファーを含む生のメッセージ
        """
        message: dict[str, Any] = json.loads(raw_message)
        if message["type"] == "offer":
            # "type": "offer" に入ってくる自分の connection_id を保存する
            self._connection_id = message["connection_id"]

    def _on_switched(self, raw_message: str):
        """
        スイッチイベントを処理します。

        :param raw_message: 生のスイッチメッセージ
        """
        message: dict[str, Any] = json.loads(raw_message)
        if message["type"] == "switched":
            self._switched = True

    def _on_notify(self, raw_message: str):
        """
        Sora からの通知イベントを処理します。

        :param raw_message: 生の通知メッセージ
        """
        message: dict[str, Any] = json.loads(raw_message)
        # "type": "notify" の "connection.created" で通知される connection_id が
        # 自分の connection_id と一致する場合に接続完了とする
        if (
            message["type"] == "notify"
            and message["event_type"] == "connection.created"
            and message["connection_id"] == self._connection_id
        ):
            print(f"Connected Sora: connection_id={self._connection_id}")
            self._connected.set()

    def _on_disconnect(self, error_code: SoraSignalingErrorCode, message: str):
        """
        切断イベントを処理します。

        :param error_code: 切断のエラーコード
        :param message: 切断メッセージ
        """
        print(f"Disconnected Sora: error_code='{error_code}' message='{message}'")
        self._connected.clear()
        self._closed.set()

    def _on_message(self, label: str, data: bytes):
        """
        受信したメッセージを処理します。

        :param label: データチャネルのラベル
        :param data: 受信したバイトデータ
        """
        print(f"Received message: label={label}, data={data.decode('utf-8')}")

    def _on_data_channel(self, label: str):
        """
        新しいデータチャネルイベントを処理します。

        :param label: データチャネルのラベル
        """
        for data_channel in self._data_channels:
            if data_channel["label"] != label:
                continue

            if data_channel["direction"] in ["sendrecv", "sendonly"]:
                self._sendable_data_channels.add(label)
                # データチャネルの準備ができたのでフラグを立てる
                self._is_data_channel_ready = True
                break


def sendrecv():
    # .env ファイルを読み込む
    load_dotenv()

    # 必須引数
    if not (raw_signaling_urls := os.getenv("SORA_SIGNALING_URLS")):
        raise ValueError("環境変数 SORA_SIGNALING_URLS が設定されていません")
    signaling_urls = raw_signaling_urls.split(",")

    if not (channel_id := os.getenv("SORA_CHANNEL_ID")):
        raise ValueError("環境変数 SORA_CHANNEL_ID が設定されていません")

    if not (messaging_label := os.getenv("SORA_MESSAGING_LABEL")):
        raise ValueError("環境変数 SORA_MESSAGING_LABEL が設定されていません")

    # オプション引数
    metadata = None
    if raw_metadata := os.getenv("SORA_METADATA"):
        metadata = json.loads(raw_metadata)

    data_channels = [{"label": messaging_label, "direction": "sendrecv"}]
    messaging_sendrecv = Messaging(signaling_urls, channel_id, data_channels, metadata)

    # Sora に接続する
    messaging_sendrecv.connect()
    try:
        while not messaging_sendrecv.closed:
            # input で入力された文字列を utf-8 でエンコードして送信
            message = input()
            messaging_sendrecv.send(message.encode("utf-8"))
    except KeyboardInterrupt:
        pass
    finally:
        messaging_sendrecv.disconnect()


if __name__ == "__main__":
    sendrecv()
