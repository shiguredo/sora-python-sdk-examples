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

from sora_sdk import Sora


class MessagingRecvonly:
    def __init__(self, signaling_urls, channel_id, labels, metadata):
        self.sora = Sora()
        self.connection = self.sora.create_connection(
            signaling_urls=signaling_urls,
            role="sendrecv",
            channel_id=channel_id,
            metadata=metadata,
            audio=False,
            video=False,
            data_channels=[{"label": label, "direction": "recvonly"} for label in labels],
            data_channel_signaling=True,
        )

        self.shutdown = False
        self.connection.on_message = self.on_message
        self.connection.on_disconnect = self.on_disconnect

    def on_disconnect(self, error_code, message):
        print(f"Sora から切断されました: error_code='{error_code}' message='{message}'")
        self.shutdown = True

    def on_message(self, label, data):
        print(f"メッセージを受信しました: label={label}, data={data}")

    def run(self):
        # Sora に接続する
        self.connection.connect()
        try:
            # Ctrl+C が押される or 切断されるまでメッセージ受信を待機
            while not self.shutdown:
                time.sleep(0.01)
        except KeyboardInterrupt:
            pass
        finally:
            # Sora から切断する（すでに切断済みの場合には無視される）
            self.connection.disconnect()


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
    default_label = os.getenv("SORA_RECVONLY_LABEL")
    default_labels = [default_label] if default_label else []
    parser.add_argument(
        "--labels",
        default=default_labels,
        required=not default_label,
        nargs="+",
        help="受信するデータチャネルのラベル名（複数指定可能）",
    )

    # オプション引数
    parser.add_argument("--metadata", default=os.getenv("SORA_METADATA"), help="メタデータ JSON")
    args = parser.parse_args()

    metadata = None
    if args.metadata:
        metadata = json.loads(args.metadata)

    messaging_recvonly = MessagingRecvonly(
        args.signaling_urls, args.channel_id, args.labels, metadata
    )
    messaging_recvonly.run()


if __name__ == "__main__":
    main()
