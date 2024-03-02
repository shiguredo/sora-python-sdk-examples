import json
import random
import time
from threading import Event
from typing import Any, Dict, List

from sora_sdk import Sora, SoraConnection, SoraSignalingErrorCode


class SoraClient:
    _sora: Sora
    _connection: SoraConnection

    _connection_id: str

    _connected: Event
    _closed: bool = False

    _data_channels: List[Dict[str, Any]]
    _sendable_data_channels: set = set()

    def __init__(
        self,
        # python 3.8 まで対応なので list[str] ではなく List[str] にする
        signaling_urls: List[str],
        channel_id: str,
        data_channels: List[Dict[str, Any]],
        metadata: Dict[str, Any],
    ):
        self._data_channels = data_channels

        self._sora = Sora()
        self._connection = self._sora.create_connection(
            signaling_urls=signaling_urls,
            role="sendrecv",
            channel_id=channel_id,
            metadata=metadata,
            audio=False,
            video=False,
            data_channels=self._data_channels,
            data_channel_signaling=True,
        )

        self.sender_id = random.randint(1, 10000)

        self._connection.on_set_offer = self._on_set_offer
        self._connection.on_notify = self._on_notify
        self._connection.on_data_channel = self._on_data_channel
        self._connection.on_message = self._on_message
        self._connection.on_disconnect = self._on_disconnect

    def connect(self):
        self._connection.connect()

        assert self._connected.wait(10), "接続に失敗しました"

    def disconnect(self):
        self._connection.disconnect()

    def send(self, data):
        # on_data_channel() が呼ばれるまではデータチャネルの準備ができていないので待機
        while not self._is_data_channel_ready and not self._closed:
            time.sleep(0.01)

        self._connection.send_data_channel(self._label, data)
        print(f"メッセージを送信しました: label={self._label}, data={data}")

    def _on_set_offer(self, raw_message: str):
        message: Dict[str, Any] = json.loads(raw_message)
        if message["type"] == "offer":
            self._connection_id = message["connectionId"]
            self._connected.set()

    def _on_notify(self, raw_message: str):
        message: Dict[str, Any] = json.loads(raw_message)
        if (
            message["type"] == "notify"
            and message["event_type"] == "connection.created"
            and message["connectionId"] == self._connection_id
        ):
            self._connected.set()

    def _on_disconnect(self, error_code: SoraSignalingErrorCode, message: str):
        print(f"Sora から切断されました: error_code='{error_code}' message='{message}'")
        self._connected.clear()
        self._closed = True

    def _on_message(self, label: str, data: bytes):
        print(f"メッセージを受信しました: label={label}, data={data.decode('utf-8')}")

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
