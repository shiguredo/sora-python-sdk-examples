import sys
import time
import uuid

from src.media_recvonly import Recvonly


def test_recvonly(setup) -> None:
    signaling_urls = setup.get("signaling_urls")
    channel_id_prefix = setup.get("channel_id_prefix")
    metadata = setup.get("metadata")

    channel_id = f"{channel_id_prefix}{__name__}_{sys._getframe().f_code.co_name}_{uuid.uuid4()}"

    recvonly = Recvonly(
        signaling_urls=signaling_urls,
        channel_id=channel_id,
        metadata=metadata,
    )

    recvonly.connect()

    time.sleep(3)

    recvonly.disconnect()
