import sys
import time
import uuid

from media_sendonly import Sendonly


def test_sendonly(setup) -> None:
    signaling_urls = setup.get("signaling_urls")
    channel_id_prefix = setup.get("channel_id_prefix")
    metadata = setup.get("metadata")

    channel_id = f"{channel_id_prefix}{__name__}_{sys._getframe().f_code.co_name}_{uuid.uuid4()}"

    sendonly = Sendonly(
        signaling_urls=signaling_urls,
        channel_id=channel_id,
        metadata=metadata,
    )

    sendonly.connect()

    time.sleep(3)

    sendonly.disconnect()
