import sys, os, struct, math, xml.etree.ElementTree as ET
root = sys.argv[1]; xml = os.path.join(root, "hand2/hand2_2/body/mjcf/right.xml"); meshdir = os.path.join(root, "hand2/hand2_2/body/meshes/right")
tree = ET.parse(xml); wb = tree.getroot().find("worldbody")
def pos(b): return [float(x) for x in b.get("pos", "0 0 0").split()]
def norm(v): return math.sqrt(sum(x*x for x in v))
def walk(b, depth=0, out=None):
    out = [] if out is None else out
    out.append((depth, b.get("name"), pos(b), [j.get("name") for j in b.findall("joint")], [s.get("name") for s in b.findall("site")], [ (g.get("type"), g.get("mesh"), g.get("contype"), g.get("conaffinity"), g.get("group")) for g in b.findall("geom")]))
    for c in b.findall("body"): walk(c, depth+1, out)
    return out
rows = walk(wb.find("body"))
print("body tree (depth, name, pos in parent, joints, sites, geoms):")
for d, n, p, j, s, g in rows: print("  "*d, n, [round(x*1000,1) for x in p], j, s, g[:2])
# finger segment lengths: proximal_abd->middle->distal->tip
names = {r[1]: r for r in rows}
def seg(a, b): return norm(pos(wb.find(f".//body[@name='{b}']"))) if wb.find(f".//body[@name='{b}']") is not None else float("nan")
for f in ["thumb", "index_finger", "middle_finger", "ring_finger", "pinky"]:
    chain = [f"r_{f}_proximal", f"r_{f}_proximal_abd", f"r_{f}_middle", f"r_{f}_distal"]
    segs = [norm(pos(wb.find(f".//body[@name='{c}']"))) for c in chain[1:] if wb.find(f".//body[@name='{c}']") is not None]
    tipsite = wb.find(f".//site[@name='r_{f}_tip']"); tip = norm([float(x) for x in tipsite.get("pos").split()]) if tipsite is not None else float("nan")
    print(f"{f:14s} segs mm {[round(s*1000,1) for s in segs]} + tip offset {round(tip*1000,1)}  => MCP->tip ~ {round((sum(segs[1:])+tip)*1000)} mm")
# fingertip width from STL bounding boxes
def stl_bbox(path):
    b = open(path, "rb").read()
    if b[:5] == b"solid" and b"facet" in b[:400]:
        import re; v = [tuple(map(float, m.groups())) for m in re.finditer(rb"vertex\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)", b)]
    else:
        n = struct.unpack("<I", b[80:84])[0]; v = []
        for i in range(n):
            o = 84 + i*50; vals = struct.unpack("<12f", b[o:o+48]); v += [vals[3:6], vals[6:9], vals[9:12]]
    xs, ys, zs = zip(*v); return [round((max(a)-min(a))*1000,1) for a in (xs, ys, zs)]
for m in ["r_index_finger_distal.STL", "r_index_finger_tip_sensor_frame.STL", "r_index_finger_middle.STL", "r_thumb_distal.STL", "r_wrist.STL", "r_mount.STL"]:
    p = os.path.join(meshdir, m); print(m, "bbox extents mm (x,y,z):", stl_bbox(p) if os.path.exists(p) else "missing")
print("geoms in file:", len(tree.getroot().findall(".//geom")), " collision geoms (contype!=0 or unspecified):", sum(1 for g in tree.getroot().findall(".//geom") if g.get("contype") != "0"))
print("default geom:", [(d.tag, d.attrib) for d in tree.getroot().find("default").iter() if d.tag == "geom"])
