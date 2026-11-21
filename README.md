# Overscan for Home Assistant

A Home Assistant integration for [Overscan](https://github.com/burkben/Overscan),
which syncs Philips Hue lights with a Samsung Tizen TV. It shows the sync state
and has a switch that starts and stops sync, so an automation can turn sync on
when the TV switches to a game console or film.

It talks to the TV over Overscan's local API on port 8765. Nothing goes through the cloud.

## Requirements

- Overscan 1.2.4 or later on the TV, opened at least once since it was
  installed. Its service then starts with the TV, so the API answers even while
  Overscan's menu is closed.
- Home Assistant 2025.2 or later, on the same network as the TV.
- A fixed IP address for the TV, for example a DHCP reservation in your router.
  If the address changes, use **Reconfigure** on the integration to enter the
  new one.

## Install

### Home Assistant Marketplace

[![Open your Home Assistant instance and open this repository in the Marketplace.](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=NullScope&repository=overscan-homeassistant&category=integration)

The button opens this repository in your Home Assistant's Marketplace
(Home Assistant 2026.11 or later). Install **Overscan**, then restart Home
Assistant. Or add it yourself:

1. Go to **Settings → Marketplace** and choose **Add from link**. This needs
   a GitHub account connected to the Marketplace.
2. Add `https://github.com/NullScope/overscan-homeassistant` as an
   **Integration**.
3. Install **Overscan**, then restart Home Assistant.

Before Home Assistant 2026.11, the Marketplace was the separately installed HACS.
There, add the link under HACS → menu → **Custom repositories** instead.

### By hand

Copy `custom_components/overscan` into the `custom_components` folder of your
Home Assistant configuration, then restart Home Assistant.

## Add the TV

[![Open your Home Assistant instance and start setting up Overscan.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=overscan)

1. On the TV, open Overscan → **Help & details → Home automation**. The page
   shows the TV's IP address and a six-character pairing code. Keep it open.
2. In Home Assistant, select the button above, or go to **Settings → Devices &
   services → Add integration** and choose **Overscan**.
3. Enter the TV's IP address.
4. Enter the pairing code from the TV. Keep **Device name** as
   `Home Assistant`, or choose another name if this TV is already paired with
   another device of that name.

The TV then shows **Registered Home Assistant**, and Home Assistant keeps the
API key it received. The key itself is never sent again: starting and stopping
sync are signed with HTTP Digest (SHA-256).

The code works only while the Home automation page is open, and only once.
After five wrong attempts, the TV shows a new one.

## Entities

| Entity | Shows or does |
| --- | --- |
| **Sync** (switch) | On while sync is switched on. Turning it on or off works like Start and Stop in the TV menu |
| **Sync state** (sensor) | Setup needed, Off, Waiting, Connecting, Streaming, Restoring lights, Retrying, Stopped or Error |
| **Receiving picture** (binary sensor) | On while picture colors are arriving from the TV |
| **Entertainment area** (sensor) | The Hue Entertainment area Overscan uses |
| **Screen** (sensor) | On, Dimmed or Off, from the TV's display state. Unknown on TVs that don't report it |
| **Service started** (diagnostic sensor) | When Overscan's service on the TV last started |

The state is read every 10 seconds and right after the switch is used. When the
TV is unplugged or off the network, the entities become unavailable.

The TV doesn't start sync while its screen is off, so an automation can't light
the room for a TV in standby. Turning the switch on then shows an error, and
the Screen sensor shows Off. Turning sync off always works. On TVs that don't
report their screen state, starting isn't blocked.

If the TV can't start sync for another reason, for example because setup isn't
finished or no room is chosen, turning the switch on shows the TV's reason.

### Example: sync while a console is on

```yaml
automation:
  - alias: Hue sync for the console
    triggers:
      - trigger: state
        entity_id: media_player.living_room_tv
        attribute: source
    actions:
      - action: >
          {{ 'switch.turn_on' if trigger.to_state.attributes.source == 'HDMI1'
             else 'switch.turn_off' }}
        target:
          entity_id: switch.overscan_sync
```

## Pair again

**Forget devices** on the TV's Home automation page removes every paired
device. The next time Home Assistant tries to start or stop sync, it shows a
notification to pair again: open the Home automation page on the TV and enter
the new code.

## Security

The API uses plain HTTP on your local network. Anyone on the network can read
the sync state. Starting and stopping need the key, which never crosses the
network, and each signed request can't be replayed, but the traffic isn't
encrypted. Use it on a network you trust. Diagnostics downloads leave the key
out.

## Development

The tests run a stand-in for the TV's API, including its Digest checks. Home
Assistant doesn't install on Windows, so run them on Linux, macOS, or in a
container:

```bash
docker run --rm -v "$PWD:/src:ro" python:3.14-slim sh -c "cp -r /src /work && cd /work && pip install -q -r requirements_test.txt && python -m pytest -q"
```

## License

MIT, like Overscan. See [LICENSE](LICENSE).
