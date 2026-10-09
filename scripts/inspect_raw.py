import json
import sys

d = json.load(open(sys.argv[1], encoding="utf-8"))
p = d["payload"]
t = p.get("_raw_text") if isinstance(p, dict) else None
if t is None:
    print(json.dumps(p, ensure_ascii=False)[:2000])
    sys.exit()
print("len:", len(t))
for marker in ["## API Response", "```json", '"success"', '{"success"', "## Complete"]:
    print(repr(marker), "->", t.find(marker))
i = t.find("```json")
if i >= 0:
    print(t[i : i + 1200])
else:
    i = t.find('{"success"')
    print(t[max(0, i - 200) : i + 1200] if i >= 0 else t[:1500])
