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

from dotenv import load_dotenv

from messaging import SoraClient


def sendrecv():
    # .env を読み込む
    load_dotenv()

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
    default_data_channels = os.getenv("SORA_DATA_CHANNELS")
    parser.add_argument(
        "--data-channels",
        default=default_data_channels,
        required=not default_data_channels,
        help='使用するデータチャネルを JSON で指定する (例: \'[{"label": "#spam", "direction": "sendrecv"}]\')',
    )

    # オプション引数
    parser.add_argument("--metadata", default=os.getenv("SORA_METADATA"), help="メタデータ JSON")
    args = parser.parse_args()

    metadata = None
    if args.metadata:
        metadata = json.loads(args.metadata)

    messaging_sendrecv = SoraClient(
        args.signaling_urls, args.channel_id, json.loads(args.data_channels), metadata
    )
    messaging_sendrecv.run()


if __name__ == "__main__":
    sendrecv()
