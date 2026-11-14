"""Switch the hand's motors off and confirm it. Use it whenever you are not sure the hand is off (after a crash, a dropped cable, a closed laptop).
The fingers go limp. usage: python scripts/hand_off.py"""
import sys, time
import wuji_sdk

m = wuji_sdk.SdkManager.instance()
hands = [d for d in m.scan() if d.device_type == wuji_sdk.DeviceType.WujiHand2]
if not hands: sys.exit("no Wuji Hand 2 found: check the network cable and the power. If the hand is holding a pose, unplug its power.")
rc = 0
for d in hands:
    h = m.connect(sn=d.sn, device_name="off"); h.disable(); time.sleep(0.4)
    sub = h.joint_diagnostics().subscribe(); fr = None; t_ = time.monotonic()
    while time.monotonic() - t_ < 1.5:
        x = sub.recv()
        if x is not None: fr = x
        elif fr is not None and time.monotonic() - t_ > 0.4: break
        else: time.sleep(0.01)
    sub.close()
    on = None if fr is None else sum(1 for e in fr.joints if e.status_word.ext_state == 2)
    print(f"{d.sn}: " + ("no answer after switching off: look at the hand" if on is None else "off, all joints limp" if on == 0 else f"{on} joints STILL ON"))
    if on != 0: rc = 1
m.disconnect_all(); sys.exit(rc)
