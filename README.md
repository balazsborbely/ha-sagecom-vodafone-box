# Sagemcom F@st CPE Home Assistant integration

This custom integration connects to Sagemcom/XMO routers on the local network. It provides status and statistics, plus explicitly triggered management actions.

## Supported devices

The integration is currently verified with these devices:

- **Sagemcom FAST3896**
  - Provider: **Vodafone Hungary**
  - Firmware: **FAST3896-15_VDFH-RDK_83.1.23**
  - Management interface: local Sagemcom/XMO REST API (`/api/v1/*`)
- **Sagemcom F@st 5670v2** (`Fast5670AXv2`)
  - Provider: **Magyar Telekom**
  - Firmware: **SGFm100330** (Telekom firmware)
  - Management interface: local Sagemcom XMO JSON-RPC API (`/cgi/json-req`, SHA-512 authentication via `sagemcom-api`)

Compatibility with other Sagemcom, Vodafone, or Telekom router models may vary because the available API fields and endpoints can differ.

## Entities

- WAN connectivity and traffic counters (received/transmitted bytes on supported models)
- Router uptime and firmware
- Public IPv4 and cable modem status
- DOCSIS downstream/upstream averages
- Active client count (with active device list attributes)
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
6. Choose **Sagemcom F@st CPE** and enter the router IP, username, and password.

## Manual installation

1. Copy `custom_components/sagecom` into the Home Assistant `config/custom_components` directory.
2. Restart Home Assistant.
3. Open **Settings > Devices & services > Add integration**.
4. Choose **Sagemcom F@st CPE** and enter the router IP, username, and password.

## Screenshots
<img width="1475" height="1250" alt="image" src="https://github.com/user-attachments/assets/fc32d125-127e-4262-9dd6-28d1c62e0c8b" />
