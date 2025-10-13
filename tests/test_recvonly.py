import time
import uuid

from recvonly import Recvonly


def test_recvonly(setup) -> None:
    signaling_urls = setup.get("signaling_urls")
    channel_id_prefix = setup.get("channel_id_prefix")
    metadata = setup.get("metadata")

    channel_id = f"{channel_id_prefix}{uuid.uuid4()}"

    with Recvonly(
        signaling_urls,
        channel_id,
        metadata=metadata,
        show_preview=False,
    ) as recvonly:
        time.sleep(5)

        stats = recvonly.get_stats()

        # transport の統計情報を取得して接続確認
        transport_stat = next(
            (stat for stat in stats if stat.get("type") == "transport"),
            None,
        )
        assert transport_stat is not None
        assert transport_stat.get("dtlsState") == "connected"
        assert transport_stat.get("iceState") == "connected"
