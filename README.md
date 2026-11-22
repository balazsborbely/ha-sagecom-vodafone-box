# Sagemcom Vodafone Home Assistant integration

This custom integration connects to Sagemcom/XMO routers on the local network. It provides status and statistics, plus explicitly triggered management actions.

## Entities

- WAN connectivity
- Router uptime and firmware
- Public IPv4 and cable modem status
- DOCSIS downstream/upstream averages
- Active client count
- 2.4 GHz and 5 GHz Wi-Fi status and traffic counters
- Active host device trackers
- Wi-Fi, LED, EasyMesh, UPnP, and firewall switches
- Reboot and reset Wi-Fi buttons

## Management services

The integration also exposes explicit services for DHCP reservations, port forwarding, firewall rules, parental control, web filtering, UPnP, reboot, and Wi-Fi reset.

Management actions are only sent when a switch, button, automation, script, or service is explicitly used. Polling and connection setup are read-only.

## HACS installation

1. Open HACS in Home Assistant.
2. Open **Integrations**, then choose **Custom repositories**.
3. Add `https://github.com/banditoth/ha-sagecom-vodafone-box` with the **Integration** category.
4. Download and restart Home Assistant.
5. Open **Settings > Devices & services > Add integration**.
6. Choose **Sagemcom Vodafone** and enter the router IP, username, and password.

## Manual installation

1. Copy `custom_components/sagecom` into the Home Assistant `config/custom_components` directory.
2. Restart Home Assistant.
3. Open **Settings > Devices & services > Add integration**.
4. Choose **Sagemcom Vodafone** and enter the router IP, username, and password.
