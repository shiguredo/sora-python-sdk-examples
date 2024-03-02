# Sora のデータチャネル機能を使ってメッセージを送信するサンプルスクリプト。
#
# コマンドライン引数で指定されたチャネルおよびラベルに、同じくコマンドライン引数で指定されたデータを送信する。
#
# 実行例:
# $ rye run python src/messaging_sendonly.py --signaling-urls wss://sora.example.com/signaling --channel-id sora --label '#foo' --data hello
import argparse
import json
import os

from dotenv import load_dotenv

from messaging import SoraClient


def sendonly():
    # .env を読み込む
    load_dotenv()

    parser = argparse.ArgumentParser()

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
    default_messaging_label = os.getenv("SORA_MESSAGING_LABEL")
    parser.add_argument(
        "--messaging-label",
        default=default_messaging_label,
        required=not default_messaging_label,
        help="送信するデータチャネルのラベル名",
    )

    default_messaging_data = os.getenv("SORA_MESSAGING_DATA")
    parser.add_argument(
        "--messaging-data",
        default=default_messaging_data,
        required=not default_messaging_data,
        help="送信するデータ",
    )

    # オプション引数
    parser.add_argument("--metadata", default=os.getenv("SORA_METADATA"), help="メタデータ JSON")
    args = parser.parse_args()

    metadata = None
    if args.metadata:
        metadata = json.loads(args.metadata)

    # data_channels 組み立て
    data_channels = [{"label": args.messaging_label, "direction": "sendonly"}]
    messaging_sendonly = SoraClient(args.signaling_urls, args.channel_id, data_channels, metadata)
    messaging_sendonly.connect()

    messaging_sendonly.send(args.data.encode("utf-8"))

    messaging_sendonly.disconnect()


if __name__ == "__main__":
    sendonly()
