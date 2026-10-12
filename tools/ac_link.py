"""Link Breeze to your Midea air conditioner, once.

Run in Terminal, from the Breeze folder: uv run python tools/ac_link.py

Finds the AC on the network and fetches its local key through Midea's SmartHome cloud, which
only hands it to the account that owns the AC. The password is typed here, never echoed and
never saved; only the AC's address and local key are kept, readable only by you.
"""

from __future__ import annotations

import asyncio
import getpass
import sys
from pathlib import Path

from msmart.cloud import CloudError, SmartHomeCloud
from msmart.discover import Discover
from msmart.lan import AuthenticationError, Security

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ac import AC_FILE, save_link  # noqa: E402  (the Breeze folder, added just above)

REGIONS = ("US", "DE", "KR")


async def main() -> None:
    devices = await Discover.discover(auto_connect=False)
    if not devices:
        sys.exit("No air conditioner found on the network. Is it on the same Wi-Fi as this Mac?")
    dev = devices[0]
    print(f"Found an air conditioner at {dev.ip}.")
    account = input("MSmartHome email: ").strip()
    password = getpass.getpass("MSmartHome password (hidden): ")
    for region in REGIONS:
        try:
            cloud = SmartHomeCloud(region, account=account, password=password)
            await cloud.login()
        except (CloudError, ValueError) as exc:
            print(f"{region}: sign in failed ({exc})")
            continue
        # The cloud knows the AC by an id made from its device id, in one byte order or the other.
        for endian in ("little", "big"):
            udpid = Security.udpid(dev.id.to_bytes(6, endian)).hex()
            try:
                token, key = await cloud.get_token(udpid, dev.id)
                await dev.authenticate(token, key)
            except (CloudError, AuthenticationError) as exc:
                print(f"{region}, {endian} byte order: {exc}")
                continue
            await dev.refresh()
            save_link({"ip": dev.ip, "port": dev.port, "id": dev.id, "token": dev.token, "key": dev.key})
            state = "on" if dev.power_state else "off"
            print(f"Linked. The air conditioner is {state}, set to {dev.target_temperature:g} °C. Saved to {AC_FILE}.")
            return
    sys.exit("Midea's cloud did not give a key for this air conditioner. Is it added in your MSmartHome app?")


if __name__ == "__main__":
    asyncio.run(main())
