import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
from app.core.config import settings

def main():
    api_key = settings.HEYGEN_API_KEY
    if not api_key or not api_key.strip():
        print("ERROR: HEYGEN_API_KEY is not configured.")
        return

    headers = {
        "X-Api-Key": api_key,
        "Accept": "application/json"
    }

    for ep in ["https://api.heygen.com/v2/avatars", "https://api.heygen.com/v3/avatars"]:
        print(f"\nQuerying {ep}...")
        try:
            r = requests.get(ep, headers=headers, timeout=30)
            print("Status code:", r.status_code)
            if r.status_code == 200:
                data = r.json().get("data", {})
                avatars = data.get("avatars", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                print(f"Total available avatars: {len(avatars)}")
                for idx, a in enumerate(avatars[:10], start=1):
                    aid = a.get("avatar_id")
                    aname = a.get("avatar_name")
                    print(f"  [{idx}] ID: {aid} | Name: {aname}")
                found_wayne = any(a.get("avatar_id") == "default_avatar_wayne" for a in avatars)
                print(f"Configured ID 'default_avatar_wayne' in list: {found_wayne}")
                return
            else:
                print("Response error:", r.text[:300])
        except Exception as e:
            print("Request failed:", e)

    print("\nTrying fallback endpoint v1/avatar.list...")
    try:
        r2 = requests.get("https://api.heygen.com/v1/avatar.list", headers=headers, timeout=15)
        print("Status code:", r2.status_code)
        if r2.status_code == 200:
            data2 = r2.json().get("data", {})
            avatars2 = data2.get("avatars", [])
            print(f"Total available avatars: {len(avatars2)}")
            for idx, a in enumerate(avatars2[:10], start=1):
                aid = a.get("avatar_id")
                aname = a.get("avatar_name")
                print(f"  [{idx}] ID: {aid} | Name: {aname}")
        else:
            print("Response error:", r2.text[:300])
    except Exception as e:
        print("Fallback request failed:", e)

if __name__ == "__main__":
    main()
