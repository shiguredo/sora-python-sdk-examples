import json
import random
import time
from threading import Event
from typing import Any

from sora_sdk import Sora, SoraConnection, SoraSignalingErrorCode

from helpers import EnvPrefixArgumentParser, json_object, resolve_channel_id


class Messaging:
    def __init__(
        self,
        signaling_urls: list[str],
        channel_id: str,
        data_channels: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ):
        self._channel_id = channel_id

        # データチャネル設定
        self._data_channels = data_channels

        # Sora 接続の初期化
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
        self._connection_id: str | None = None

        # 接続状態の管理
        self._connected = Event()
        self._switched: bool = False
        self._closed = Event()
        self._default_connection_timeout_s: float = 10.0

        # データチャネルの管理
        self._label = data_channels[0]["label"]
        self._sendable_data_channels: set = set()
        self._is_data_channel_ready = False

        # 送信者の識別用 ID
        self.sender_id = random.randint(1, 10000)

        # コールバック関数の登録
        self._connection.on_set_offer = self._on_set_offer
        self._connection.on_switched = self._on_switched
        self._connection.on_notify = self._on_notify
        self._connection.on_data_channel = self._on_data_channel
        self._connection.on_message = self._on_message
        self._connection.on_disconnect = self._on_disconnect

    @property
    def closed(self):
        return self._closed.is_set()

    def connect(self):
        self._connection.connect()

        assert self._connected.wait(self._default_connection_timeout_s), (
            "Could not connect to Sora."
        )

    def disconnect(self):
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
        # on_data_channel() が呼ばれるまではデータチャネルの準備ができていないので待機
        while not self._is_data_channel_ready and not self._closed.is_set():
            time.sleep(0.01)

        self._connection.send_data_channel(self._label, data)

    def _on_set_offer(self, raw_message: str):
        message: dict[str, Any] = json.loads(raw_message)
        if message["type"] == "offer":
            # "type": "offer" に入ってくる自分の connection_id を保存する
            self._connection_id = message["connection_id"]

    def _on_switched(self, raw_message: str):
        message: dict[str, Any] = json.loads(raw_message)
        if message["type"] == "switched":
            self._switched = True

    def _on_notify(self, raw_message: str):
        message: dict[str, Any] = json.loads(raw_message)
        # "type": "notify" の "connection.created" で通知される connection_id が
        # 自分の connection_id と一致する場合に接続完了とする
        if (
            message["type"] == "notify"
            and message["event_type"] == "connection.created"
            and message["connection_id"] == self._connection_id
        ):
            print(
                f"Connected Sora: channel_id={self._channel_id}, connection_id={self._connection_id}"
            )
            self._connected.set()

    def _on_disconnect(self, error_code: SoraSignalingErrorCode, message: str):
        print(f"Disconnected Sora: error_code='{error_code}' message='{message}'")
        self._connected.clear()
        self._closed.set()

    def _on_message(self, label: str, data: bytes):
        print(f"Received message: label={label}, data={data.decode('utf-8')}")

    def _on_data_channel(self, label: str):
        for data_channel in self._data_channels:
            if data_channel["label"] != label:
                continue

            if data_channel["direction"] in ["sendrecv", "sendonly"]:
                self._sendable_data_channels.add(label)
                # データチャネルの準備ができたのでフラグを立てる
                self._is_data_channel_ready = True
                break


def _parse_args(argv: list[str] | None = None):
    parser = EnvPrefixArgumentParser(
        env_prefix="SORA_",
        description="Sora data channel messaging sample application",
    )
    parser.add_argument(
        "--signaling-url",
        dest="signaling_urls",
        nargs="+",
        metavar="URL",
        help="Sora signaling URL(s) to connect to. Multiple URLs can be specified for failover purposes. Example: --signaling-url wss://example.com/signaling --signaling-url wss://backup.com/signaling",
    )
    parser.add_argument(
        "--channel-id",
        dest="channel_id",
        help="Channel ID to connect to. This identifies the Sora channel for the messaging session. Either this or --channel-id-prefix must be specified.",
    )
    parser.add_argument(
        "--channel-id-prefix",
        dest="channel_id_prefix",
        help="Prefix used to generate a unique channel ID. A random suffix will be appended to this prefix. Use this when you want to create a new channel dynamically.",
    )
    parser.add_argument(
        "--messaging-label",
        dest="messaging_label",
        help="Label for the data channel. This label is used to identify the data channel for sending and receiving messages. Must be specified.",
    )
    parser.add_argument(
        "--messaging-direction",
        dest="messaging_direction",
        choices=["sendrecv", "sendonly", "recvonly"],
        default="sendrecv",
        help="Direction of the data channel communication. 'sendrecv' allows both sending and receiving, 'sendonly' allows only sending, and 'recvonly' allows only receiving messages. Default is 'sendrecv'.",
    )
    parser.add_argument(
        "--metadata",
        dest="metadata",
        type=json_object,
        help='Optional metadata to send during connection establishment, specified as a JSON string. This metadata is sent to the Sora server and can be used for custom connection handling. Example: \'{"key": "value"}\'',
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    signaling_urls = args.signaling_urls
    if not signaling_urls:
        raise ValueError("Signaling URL is not specified")

    # channel_id または channel_id_prefix から実際の channel_id を解決
    channel_id = resolve_channel_id(args.channel_id, args.channel_id_prefix)

    if not args.messaging_label:
        raise ValueError("Data channel label is not specified")

    data_channels = [{"label": args.messaging_label, "direction": args.messaging_direction}]
    messaging_sendrecv = Messaging(signaling_urls, channel_id, data_channels, args.metadata)

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
    main()
