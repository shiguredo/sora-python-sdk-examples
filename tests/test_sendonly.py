import time
import uuid

from sendonly import Sendonly


def test_sendonly(setup) -> None:
    signaling_urls = setup.get("signaling_urls")
    channel_id_prefix = setup.get("channel_id_prefix")
    metadata = setup.get("metadata")

    channel_id = f"{channel_id_prefix}{uuid.uuid4()}"

    with Sendonly(
        signaling_urls,
        channel_id,
        metadata=metadata,
        fake_audio=True,
        fake_video=True,
    ) as sendonly:
        time.sleep(5)

        stats = sendonly.get_stats()

        # audio の outbound-rtp 統計情報を取得してテスト
        audio_stat = next(
            (
                stat
                for stat in stats
                if stat.get("type") == "outbound-rtp" and stat.get("kind") == "audio"
            ),
            None,
        )
        assert audio_stat is not None
        assert audio_stat.get("packetsSent") > 0
        assert audio_stat.get("bytesSent") > 0

        # video の outbound-rtp 統計情報を取得してテスト
        video_stat = next(
            (
                stat
                for stat in stats
                if stat.get("type") == "outbound-rtp" and stat.get("kind") == "video"
            ),
            None,
        )
        assert video_stat is not None
        assert video_stat.get("packetsSent") > 0
        assert video_stat.get("bytesSent") > 0

        # transport の統計情報を取得して接続確認
        transport_stat = next(
            (stat for stat in stats if stat.get("type") == "transport"),
            None,
        )
        assert transport_stat is not None
        assert transport_stat.get("dtlsState") == "connected"
        assert transport_stat.get("iceState") == "connected"
