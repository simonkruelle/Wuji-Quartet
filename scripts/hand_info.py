"""Read-only check of the real hand(s): finds every Wuji Hand 2 on the network, prints serial number, side, IP and firmware, counts the
joints that are online and reads one joint-state frame. It does NOT enable the motors and sends no command.

  python scripts/hand_info.py            (on the RDK X5: ./wq hand python scripts/hand_info.py)"""
import os, time
os.environ.setdefault("WUJI_TELEMETRY_DISABLE", "1")
import numpy as np
import wuji_sdk

HELP = ("no Wuji Hand 2 found. Check in this order: hand powered (status light on the back of the hand), network cable, "
        "this computer's wired port on 192.168.1.x (bash scripts/hand_net.sh), `ping 192.168.1.111` (right hand; left is .110).")
manager = wuji_sdk.SdkManager.instance()
try:
    hands = [d for d in manager.scan() if d.device_type == wuji_sdk.DeviceType.WujiHand2]
    if not hands: raise SystemExit(HELP)
    side = lambda sn: {"J": "LEFT", "K": "RIGHT"}.get(str(sn)[3:4].upper(), "side unknown")      # 4th character of the serial number
    for d in hands: print(f"found  SN={d.sn}  {side(d.sn)} hand  ip={d.ip}  firmware={d.firmware_version}")
    if len({d.ip for d in hands}) < len(hands): print("WARNING: two hands report the same IP address; one of them needs a new one before both can be used")
    for d in hands:
        hand = manager.connect(sn=d.sn, device_name="info_" + d.sn[-4:])
        print(f"{d.sn}: joints online:", int(hand.online_joints_count().get()), "of 20")
        sub = hand.joint_states().subscribe(); t0 = time.monotonic(); frame = None
        while frame is None and time.monotonic() - t0 < 2.0:
            frame = sub.recv(); time.sleep(0.001)
        sub.close()
        if frame is None: print("no joint states within 2 s")
        else:
            q = np.full(20, np.nan)
            for j in frame.joints: q[wuji_sdk.WujiHand2.nid_to_joint_index(j.nid)] = j.position
            print("joint angles in rad (rows: thumb, index, middle, ring, pinky):"); print(np.round(q.reshape(5, 4), 2))
finally:
    manager.disconnect_all()
