"""Run in Terminal, from the Breeze folder: uv run python tools/ac_link.py

Find the Midea AC, fetch its local key through Midea's SmartHome cloud, save it 0600."""
import asyncio, getpass, json, os, sys
from pathlib import Path
from msmart.discover import Discover
from msmart.cloud import SmartHomeCloud, CloudError
from msmart.lan import Security, AuthenticationError

OUT = Path.home() / ".config/breeze/ac.json"

async def main():
    devices = await Discover.discover(auto_connect=False)
    if not devices:
        sys.exit("No AC found on the network.")
    dev = devices[0]
    print(f"found: {type(dev).__name__} at {dev.ip}:{dev.port} version {dev.version}")
    # Midea only gives the key to the account that owns the AC. The password is typed here,
    # never echoed, never saved; only the AC's local key is kept.
    account = input("MSmartHome email: ").strip()
    password = getpass.getpass("MSmartHome password (hidden): ")
    for region in ("US", "DE", "KR"):
        try:
            cloud = SmartHomeCloud(region, account=account, password=password)
            await cloud.login()
        except (CloudError, ValueError) as e:
            print(f"{region}: login failed ({e})"); continue
        for endian in ("little", "big"):
            udpid = Security.udpid(dev.id.to_bytes(6, endian)).hex()
            try:
                token, key = await cloud.get_token(udpid, dev.id)
            except CloudError as e:
                print(f"{region}/{endian}: no key ({e})"); continue
            try:
                await dev.authenticate(token, key)
            except AuthenticationError:
                print(f"{region}/{endian}: key rejected"); continue
            await dev.refresh()
            OUT.parent.mkdir(mode=0o700, exist_ok=True)
            fd = os.open(OUT, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump({"ip": dev.ip, "port": dev.port, "id": dev.id, "token": dev.token, "key": dev.key}, f)
            print(f"linked via {region}. power={getattr(dev, 'power_state', '?')} "
                  f"target={getattr(dev, 'target_temperature', '?')} indoor={getattr(dev, 'indoor_temperature', '?')}")
            return
    sys.exit("Could not get a key from Midea's cloud.")

asyncio.run(main())
