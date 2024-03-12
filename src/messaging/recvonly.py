import argparse
import json
import os
import time

from dotenv import load_dotenv

from messaging import Messaging


def recvonly():
    # .env ファイルを読み込む
    load_dotenv()

    parser = argparse.ArgumentParser()

    # 必須引数
    default_signaling_urls = None
    if urls := os.getenv("SORA_SIGNALING_URLS"):
        # カンマ区切りで複数指定可能
        default_signaling_urls = urls.split(",")
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
        type=str,
        nargs="+",
        required=not default_messaging_label,
        help="データチャネルのラベル名",
    )

    # オプション引数
    parser.add_argument("--metadata", default=os.getenv("SORA_METADATA"), help="メタデータ JSON")
    args = parser.parse_args()

    metadata = {}
    if args.metadata:
        metadata = json.loads(args.metadata)

    data_channels = [{"label": args.messaging_label, "direction": "recvonly"}]
    messaging_recvonly = Messaging(
        args.signaling_urls,
        args.channel_id,
        data_channels,
        metadata,
    )

    # Sora に接続する
    messaging_recvonly.connect()
    try:
        # Ctrl+C が押される or 切断されるまでメッセージ受信を待機
        while not messaging_recvonly.closed:
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        # Sora から切断する（すでに切断済みの場合には無視される）
        messaging_recvonly.disconnect()


if __name__ == "__main__":
    recvonly()
