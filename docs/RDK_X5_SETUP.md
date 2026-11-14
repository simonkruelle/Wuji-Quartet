# RDK X5 setup: from the sealed box to a hand that answers

The D-Robotics RDK X5 is our robot computer. It sits next to the hand, is wired to it, and plays the plans.

**Everything here is done from a Mac terminal. The board needs no screen and no keyboard.**

**Status, 14 Nov 2026.** Written from the official D-Robotics and Wuji documentation and from D-Robotics' own Docker installer (links at the end). **None of it has run on our board yet.** What we could test without the board is marked *tested*. Please correct this page as you go.

## Short version

```bash
# on the Mac (en7 = your USB Ethernet adapter, see step 3)
sudo ifconfig en7 alias 192.168.127.100 255.255.255.0
ssh -A sunrise@192.168.127.10                    # password: sunrise

# on the board
sudo wifi_connect "NETWORK NAME" "PASSWORD"
sudo apt update && sudo apt install -y git
git clone git@github.com:simonkruelle/Wuji-Quartet.git ~/Wuji-Quartet
cd ~/Wuji-Quartet && sudo bash scripts/rdk_setup.sh
exit                                             # then ssh in again
cd ~/Wuji-Quartet && ./wq build && ./wq check
```

| Step | What | Time | Checked how |
|---|---|---|---|
| 1 | Flash the microSD card | 15 min | from the docs |
| 2 | First boot | 2 min | from the docs |
| 3 | First login from the Mac | 5 min | from the docs; Mac commands not yet tried by us |
| 4 | Wi-Fi, password | 5 min | from the docs |
| 5 | Get the repo onto the board | 5 min | standard ssh and git |
| 6 | Docker: `scripts/rdk_setup.sh` | 5 min | *tested* in a clean Ubuntu 22.04 container; not on the board |
| 7 | Build the image, self-check | 10 min | image *tested* on a PC (x86); every package has an arm64 build |
| 8 | Network to the hand | 2 min | addresses from the Wuji docs; script syntax *tested* |
| 9 | Connect the hand, read-only check | 5 min | script *tested* without a hand |
| 10 | Piano (MIDI) | 2 min | from our scripts |

<img src="wiring.png" width="880" alt="Wiring: laptops by Wi-Fi to the RDK X5, RDK X5 by Ethernet to the hand, separate power supplies, piano by USB">

---

## What you need

| Item | Detail | Source |
|---|---|---|
| USB-C power supply, **5 V / 5 A** | into the **power** USB-C port (No. 1). A laptop USB port is not enough: the board shuts down or reboots in a loop | D-Robotics |
| microSD card, **16 GB or more** | 16 GB is D-Robotics' minimum. We suggest 32 GB: the system plus our 1.4 GB image | D-Robotics / our suggestion |
| One way to log in the first time | a USB-C Ethernet adapter (3A), **or** a micro-USB cable (3B), **or** a USB-C cable (3C) | |
| Ethernet cable | the hand ships with one (shielded Cat5e, 2 m) | Wuji |

The board's ports, from the official interface list: **1** power (USB-C) · **3** QuickLink (USB-C, device mode) · **4** debug serial (micro-USB) · **6** Gigabit Ethernet · **7** four USB 3.0 type A · **10** HDMI · **13** microSD slot, on the **bottom**.

A monitor probably does not help with the server image: D-Robotics' docs say the X5 does not support a text terminal on its display output.

---

## 1 · Flash the microSD card

1. Image (server, no desktop), RDK OS 3.5.0, based on Ubuntu 22.04, 2.2 GB:

   ```
   https://archive.d-robotics.cc/downloads/os_images/rdk_x5/rdk_os_3.5.0-2026-4-9/rdk-x5-ubuntu22-preinstalled-server-3.5.0-arm64.img.xz
   ```

2. Check the download:

   ```bash
   md5 rdk-x5-ubuntu22-preinstalled-server-3.5.0-arm64.img.xz
   # expected: ec3aac7fff7ccd807d1e23a04edd115b
   ```

3. Write it to the card. D-Robotics names **RDK Studio** (Windows and macOS, https://developer.d-robotics.cc/en/rdkstudio) and **Rufus** (Windows). balenaEtcher also writes `.img.xz` files. If your tool wants a plain `.img`, unpack first: `xz -dk <file>.img.xz`.

4. Eject the card properly.

## 2 · First boot

1. Push the card into the slot on the **bottom** of the board. Never pull or insert the card while the board is on.
2. Plug the 5 V / 5 A supply into the **power** USB-C port (No. 1), not the QuickLink port (No. 3).
3. Wait about a minute. The first boot sets itself up for about 45 seconds. The green power light and the orange light blink when the supply is fine.

## 3 · First login from the Mac

Default accounts (change the password in step 4): `sunrise` / `sunrise` and `root` / `root`.

**A · Ethernet adapter (recommended).** Out of the box the board's wired port has the fixed address **192.168.127.10**, mask 255.255.255.0. Cable the Mac's USB-C Ethernet adapter to the board, then:

```bash
networksetup -listallhardwareports                        # find the adapter, e.g. "USB 10/100/1000 LAN ... Device: en7"
sudo ifconfig en7 alias 192.168.127.100 255.255.255.0     # use your device name; gone after unplugging
ping -c 3 192.168.127.10
ssh -A sunrise@192.168.127.10                             # password: sunrise
```

Your Wi-Fi and internet on the Mac keep working. If the ping fails, set the address in System Settings → Network → the adapter → Details → TCP/IP → Configure IPv4 **Manually** → `192.168.127.100`, mask `255.255.255.0`, router empty.

**B · Serial console over micro-USB.** Cable from the board's port No. 4 to the Mac. Settings: 115200 baud, 8 data bits, no parity, 1 stop bit.

```bash
ls /dev/cu.*                                   # a new entry appears: cu.usbserial-XXXX or cu.wchusbserialXXXX
screen /dev/cu.usbserial-XXXX 115200           # press Enter; log in as root / root. Leave with Ctrl-A, then K, then y
```

The adapter chip is a CH340. If no new entry appears, install the CH340 driver from its maker (WCH). Do step 4 in this console, then switch to `ssh` over Wi-Fi.

**C · USB-C cable to the QuickLink port (No. 3).** The board offers a virtual network card there with the address **192.168.128.10**. If the Mac shows a new network interface, give it `192.168.128.100` as in A and `ssh sunrise@192.168.128.10`. Whether macOS accepts this card is unknown to us.

## 4 · Wi-Fi and password

On the board:

```bash
sudo nmcli device wifi rescan
sudo nmcli device wifi list
sudo wifi_connect "NETWORK NAME" "PASSWORD"      # prints: Device 'wlan0' successfully activated
hostname -I                                       # the address on the Wi-Fi: write it on a sticker on the board
passwd                                            # the default password is public; change it on a shared network
sudo passwd root
date                                              # must show today's date, otherwise downloads fail
```

From any laptop on the same Wi-Fi: `ssh -A sunrise@<Wi-Fi address>`. Test this now, because step 8 takes the Ethernet cable away.

| If | Then |
|---|---|
| laptops cannot reach the board over Wi-Fi | guest networks often block device-to-device traffic. Use a phone hotspot for laptops and board, or a small Ethernet switch |
| the Wi-Fi itself uses 192.168.1.x | it collides with the hand's addresses (step 8). Use another network or a hotspot |
| `apt` reports a missing key (`NO_PUBKEY`) | `sudo wget -O /usr/share/keyrings/sunrise.gpg http://archive.d-robotics.cc/keys/sunrise.gpg` (D-Robotics FAQ) |

## 5 · Get the repo onto the board

The repository is private. Pick one way.

**A · Lend the board your Mac's GitHub key (nothing is stored on the board).** This is what `-A` in `ssh -A` does.

```bash
# on the Mac, before you ssh in
ssh-add -l                                   # must list a key. "no identities"? run: ssh-add
ssh -A sunrise@<board address>

# on the board
sudo apt update && sudo apt install -y git
ssh -T git@github.com                        # type yes; must answer: Hi <your GitHub name>!
git clone git@github.com:simonkruelle/Wuji-Quartet.git ~/Wuji-Quartet
```

Later `git pull` and `git push` on the board work the same way, from any teammate's `ssh -A` session.

**B · Copy the folder from the Mac (no GitHub on the board).**

```bash
scp -r ~/Wuji-Quartet sunrise@<board address>:~/        # about 120 MB
```

<details><summary>C · A key of the board's own, so it can pull without a laptop</summary>

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519 && cat ~/.ssh/id_ed25519.pub
```

Paste the printed line into GitHub → Wuji-Quartet → Settings → Deploy keys → Add deploy key (tick "Allow write access" if the board should push logs). Then clone as in A.

</details>

## 6 · Docker

```bash
cd ~/Wuji-Quartet
sudo bash scripts/rdk_setup.sh
exit                                    # log out and ssh in again, so you may run docker
```

The script must end with `ok: docker pulled and ran a test container`.

Why a script and not Docker's usual one-line install: the RDK X5's kernel lacks parts of the firewall that Docker expects, and Docker refuses to start. D-Robotics' own installer works around it. Our script does the same three things and nothing else:

| What | Why |
|---|---|
| installs Ubuntu's `docker.io` | what D-Robotics installs |
| switches the firewall tool to `iptables-legacy` | otherwise: `iptables (nf_tables): Could not fetch rule set generation id` |
| sets `allow-direct-routing` and `ip6tables: false` in `/etc/docker/daemon.json`, only if the kernel modules are missing | otherwise: `can't initialize iptables table 'raw'` |

It leaves out the Chinese registry mirror and DNS servers that D-Robotics' installer adds. If Docker still does not start, the script retries with Docker's firewall and bridge network switched off. We lose nothing: `./wq` only uses the board's own network.

D-Robotics lists as required for Docker on the X5: **RDK OS 3.3.3 or newer** (ours is 3.5.0) and **MiniBoot of 3 Sep 2025 or newer**. MiniBoot is the boot firmware on the board itself, not on the card. If the script stops with "Docker still does not start", update it with D-Robotics' tool, `sudo rdk-miniboot-update`, reboot, and run the script again.

<details><summary>If Docker cannot be made to work: install without it</summary>

Ubuntu 22.04 has Python 3.10, and MuJoCo 3.17 needs 3.11 or newer, so use `uv` to get Python 3.13:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh && source ~/.bashrc
cd ~/Wuji-Quartet
uv venv --python 3.13 .venv && source .venv/bin/activate
uv pip install -r requirements.txt
python scripts/play_on_hand.py plans/k265_fixed/theme_q_1khz.npz --dry-run --yes --end 3
```

Then run every `./wq hand python …` command below as plain `python …`.

</details>

## 7 · Build the image and check it

```bash
cd ~/Wuji-Quartet
./wq build          # downloads about 1 GB; 5 to 15 min depending on the network
./wq check
```

`./wq check` must print these lines among others:

```
python 3.13.x aarch64 | mujoco 3.17.0 | wuji-sdk import ok
ok: 36.6 s plan, 20 actuators, 88 keys
[dry-run] fake hand, first-order lag 30 ms
streamed 5100 frames, skipped 0 (late host)
```

"skipped" counts 1 kHz frames the computer was too late for. A few are harmless. Hundreds mean the board is too busy: close other programs.

<details><summary>Slow network at the venue? Build on an Apple-silicon Mac and send the image</summary>

Apple-silicon Macs and the RDK X5 are both arm64, so the image is the same. On the Mac, with Docker Desktop:

```bash
./wq build
docker save wuji-quartet:local | ssh sunrise@<board address> docker load
```

</details>

## 8 · Network to the hand

The hand has a **fixed address and no DHCP** (Wuji docs):

| | Right hand | Left hand |
|---|---|---|
| Address | **192.168.1.111** | 192.168.1.110 |
| Subnet mask | 255.255.255.0 | 255.255.255.0 |
| Port | UDP 50001 | UDP 50001 |

The board's wired port is on 192.168.127.x, so it cannot see the hand yet. Log in over **Wi-Fi**, move the Ethernet cable from the Mac to the hand (hand still **unpowered**, see step 9), and run:

```bash
cd ~/Wuji-Quartet
bash scripts/hand_net.sh            # adds 192.168.1.50/24 to eth0 and pings the hand
```

This lasts until the board reboots; run it again after each boot. It adds an address and no gateway, so the internet stays on Wi-Fi and the 192.168.127.10 address keeps working.

<details><summary>Make it permanent (D-Robotics' method)</summary>

Edit the `eth0` block in `/etc/network/interfaces` and restart the network. Leave out any `gateway` line, or the board will try to reach the internet through the hand:

```
auto eth0
iface eth0 inet static
    address 192.168.1.50
    netmask 255.255.255.0
```

```bash
sudo restart_network
```

After this the board no longer answers on 192.168.127.10.

</details>

## 9 · Connect the hand and check it (nothing moves)

Order matters (Wuji docs). Neither cable may be plugged or unplugged while the hand is powered.

1. Ethernet cable: hand to the board's Ethernet port.
2. XT30 power cable into the **hand first**.
3. Then the 12 V / 20 A adapter into the wall. The adapter's mains cable has a Chinese plug: bring a travel adapter.
4. Status light on the back of the hand: blue breathing (self-check), then white breathing (ready). If it is not white after 30 seconds, see Wuji's troubleshooting page.

```bash
bash scripts/hand_net.sh                       # "hand answers at 192.168.1.111 (right hand)"
./wq hand python scripts/hand_info.py          # read-only: serial number, firmware, 20 of 20 joints, joint angles
```

Write the firmware version into the team chat. Position mode needs a newer firmware than MIT mode, and Wuji's two pages disagree on which (2.5.1 is listed as current for Hand 2.2, the SDK example asks for 3.0.0). MIT mode is our default and works on both.

To power down: stop the program (Ctrl-C disables the hand), wait until the hand is still, unplug the adapter from the wall, then the cables.

## 10 · Piano

Plug the piano's USB-MIDI socket into one of the board's USB-A ports.

```bash
ls /dev/snd/                       # a new entry like midiC1D0 appears
./wq hand amidi -l                 # lists the keyboard by name
```

Use that device name in the runbook: `--midi-dev /dev/snd/midiC1D0`.

**Next: [RUNBOOK.md](RUNBOOK.md)**, from the first motion in the air to the full piece.

---

## No RDK X5? An Apple-silicon Mac can drive the hand directly

Wuji publishes its SDK for macOS on Apple silicon (not for Intel Macs). Docker on a Mac cannot reach the hand, so use the native install from the README, then:

1. USB-C Ethernet adapter to the hand: `sudo ifconfig en7 alias 192.168.1.50 255.255.255.0` (your device name).
2. `ping 192.168.1.111`, then `python scripts/hand_info.py`. If macOS asks whether to allow incoming connections, choose Allow.
3. Live MIDI scoring in our scripts is Linux-only. On a Mac record with any MIDI app and score the file with `scripts/score_midi.py`, and calibrate with `--manual`.

## Sources

- D-Robotics RDK X5: [hardware interfaces](https://developer.d-robotics.cc/rdk_x_doc/en/Quick_start/hardware_introduction/rdk_x5) · [flashing](https://d-robotics.github.io/rdk_doc/en/Quick_start/install_os/rdk_x5/system_burn) · [remote login](https://developer.d-robotics.cc/rdk_x_doc/en/Quick_start/remote_login) · [network](https://d-robotics.github.io/rdk_doc/en/System_configuration/network_blueteeth) · [FAQ](https://developer.d-robotics.cc/rdk_x_doc/en/FAQ/hardware_and_system) · [image server](https://archive.d-robotics.cc/downloads/os_images/rdk_x5/)
- D-Robotics' Docker installer for RDK boards: [RDK_Docker_Tools](https://gitea.d-robotics.cc/chao.wu/RDK_Docker_Tools) (`install_docker/install_docker.sh`)
- Wuji Hand 2: [quick start](https://docs.wuji.tech/docs/en/wuji-hand/latest/quick-start.md) · [electrical and network](https://docs.wuji.tech/docs/en/wuji-hand/latest/electrical-network-integration.md) · [SDK in Docker](https://docs.wuji.tech/docs/en/wuji-sdk/latest/docker-deployment.md) · [troubleshooting](https://docs.wuji.tech/docs/en/wuji-hand/latest/troubleshooting.md)
