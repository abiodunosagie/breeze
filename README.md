<h1 align="center">Breeze</h1>

<p align="center">
  A native Mac remote for Midea air conditioners.<br>
  Menu bar panel, a full hand remote on screen, and live room temperature, all over your home Wi-Fi.
</p>

## What it does

**Menu bar**
- The air conditioner icon shows the set temperature while the AC runs, like `16°`.
- Click it for a dark panel: room and outdoor temperature, power, a temperature slider, Mode, Fan, Sleep and Airflow, plus Eco, Flash, Turbo, the unit's light and an off timer.
- Air flows out of the drawn indoor unit while it runs, coloured by mode (cool blue, dry teal, fan white, auto violet, heat amber, green while it cleans itself), faster with the fan and swaying with the louvers.

**Window remote**
- Modelled key for key on the Midea hand remote: LCD with segment digits, power, Mode, AI (Eco), the ring with up, down, SET, OK and the timer, fan, Swing, Sleep, Cool/Heat Flash, LED, Fresh and the child lock.
- Keys sink when pressed and the screen lights up, like the real remote's backlight.

**Careful by design**
- While the AC cleans itself, every key but power is refused, so a stray click cannot stop the clean.
- Each control shows only what your unit supports. Settings changed quickly (a slider drag) go out as one command.

## How it works

```
 Breeze.app (SwiftUI + AppKit)
 └─ WebSocket, 127.0.0.1 only, token per launch
        │
 Helper (Python, asyncio) ── msmart-ng ──▶ Midea AC on your Wi-Fi (local protocol, encrypted)
```

Midea's newer units encrypt their local protocol with a token and key that only Midea's cloud hands out, and only to the account that owns the unit. Breeze fetches them once, when you link the AC, and from then on talks to it directly on your network. It does not use the cloud to control it.

## Requirements

- macOS 15 or later on Apple Silicon
- Xcode command line tools and [uv](https://docs.astral.sh/uv/)
- A Midea air conditioner with Wi-Fi, set up once in the MSmartHome app on 2.4 GHz Wi-Fi

## Build and link

```sh
cd breeze
./build-app.sh
uv run python tools/ac_link.py   # once: sign in with your MSmartHome account
open ~/Applications/Breeze.app
```

`tools/ac_link.py` asks for your MSmartHome email and password in Terminal, never echoes or stores the password, and saves only the AC's local key to `~/.config/breeze/ac.json`, readable only by you. If your account signs in by email code, set a password in the MSmartHome app first.

## Privacy and security

- The helper listens on 127.0.0.1 only, checks Host and Origin, and needs the random token the app makes at launch, so other apps and websites cannot reach the AC through it.
- The AC's key never leaves the helper: not in messages to the app, not in logs.

## Development

```sh
uv sync
uv run pytest
./build-app.sh
```

```
mac/             SwiftUI and AppKit app
server.py        helper: WebSocket API
ac.py            the air conditioner: state, checked changes, timer
breeze.py        helper entry point
tools/ac_link.py one time link with your MSmartHome account
```

## License

[MIT](LICENSE)
