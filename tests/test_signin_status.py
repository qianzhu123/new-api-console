import json

import app


SIGNED = "\u5df2\u7b7e\u5230"
UNSIGNED = "\u672a\u7b7e\u5230"


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_ambiguous_legacy_name_status_does_not_mark_duplicate_accounts_signed(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "SIGNIN_PATH", tmp_path / "signin_status.json")
    monkeypatch.setattr(app, "STATUS_CACHE_PATH", tmp_path / "status_cache.json")
    write_json(
        app.SIGNIN_PATH,
        {
            "date": app.today_str(),
            "accounts": {
                "qianzhu": {
                    "status": SIGNED,
                    "updated_at": f"{app.today_str()} 08:00:00",
                }
            },
        },
    )

    accounts = [
        {"account_index": 3, "name": "qianzhu", "enabled": True},
        {"account_index": 9, "name": "qianzhu", "enabled": True},
    ]

    public_accounts = app.build_public_accounts(accounts)

    assert [item["signin_status"] for item in public_accounts] == [UNSIGNED, UNSIGNED]
