"""恢复 site_info.json 中部分地址的 pinned / checkin_mode。

规则：
- 置顶：session.json 里账号数最多的 18 个 base_url。
- 手动签到：从非置顶的 19 个里取账号数最少的 9 个（单账号地址优先，避免误检）。
- 其它地址保持 enabled（默认）。
- 已有 remark / special_info / display_color 不动。
"""
import json
import pathlib
import sys

ROOT = pathlib.Path("D:/code/myweb/qiandao")
DATA = ROOT / "data"
SESSION = DATA / "session.json"
SITE_INFO = DATA / "site_info.json"

PINNED_COUNT = 18
MANUAL_COUNT = 9


def main():
    cfg = json.loads(SESSION.read_text(encoding="utf-8"))
    accounts = cfg.get("accounts", [])

    url_counts: dict[str, int] = {}
    url_first_seen: dict[str, int] = {}
    for i, acc in enumerate(accounts):
        url = (acc.get("base_url") or "").strip()
        if not url:
            continue
        url_counts[url] = url_counts.get(url, 0) + 1
        url_first_seen.setdefault(url, i)

    # 排序：账号数 desc，相同则首次出现顺序 asc
    ranked = sorted(url_counts.keys(), key=lambda u: (-url_counts[u], url_first_seen[u]))
    pinned_urls = set(ranked[:PINNED_COUNT])
    non_pinned = [u for u in ranked if u not in pinned_urls]
    # 手动签到取账号数最少的 MANUAL_COUNT 个
    non_pinned_sorted = sorted(non_pinned, key=lambda u: (url_counts[u], url_first_seen[u]))
    manual_urls = set(non_pinned_sorted[:MANUAL_COUNT])

    print(f"置顶 {len(pinned_urls)} 个:")
    for u in sorted(pinned_urls, key=lambda x: (-url_counts[x], url_first_seen[x])):
        print(f"  {u} (count={url_counts[u]})")
    print()
    print(f"手动签到 {len(manual_urls)} 个:")
    for u in sorted(manual_urls, key=lambda x: (url_counts[x], url_first_seen[x])):
        print(f"  {u} (count={url_counts[u]})")
    print()
    other = [u for u in ranked if u not in pinned_urls and u not in manual_urls]
    print(f"其它 {len(other)} 个保持 enabled:")
    for u in other:
        print(f"  {u} (count={url_counts[u]})")

    if SITE_INFO.exists():
        store = json.loads(SITE_INFO.read_text(encoding="utf-8"))
    else:
        store = {"sites": {}}
    sites = store.setdefault("sites", {})

    now = "2026-08-24 18:00:00"
    changed = []
    for url in pinned_urls:
        entry = sites.setdefault(url, {})
        if not entry.get("pinned"):
            entry["pinned"] = True
            entry["pinned_updated_at"] = now
            entry["updated_at"] = now
            changed.append(f"pinned: {url}")
    for url in manual_urls:
        entry = sites.setdefault(url, {})
        if entry.get("checkin_mode") != "manual":
            entry["checkin_mode"] = "manual"
            entry["checkin_mode_updated_at"] = now
            entry["updated_at"] = now
            changed.append(f"checkin_mode=manual: {url}")

    if changed:
        SITE_INFO.write_text(
            json.dumps(store, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print()
    print(f"写入 {len(changed)} 项变更到 {SITE_INFO}")
    for c in changed:
        print(f"  {c}")
    if not changed:
        print("  (无变化)")


if __name__ == "__main__":
    sys.exit(main())
