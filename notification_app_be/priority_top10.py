import json
from datetime import datetime, timezone
from pathlib import Path

TYPE_WEIGHT = {"Placement": 3, "Result": 2, "Event": 1}


def load_notifications(path):
    data = json.loads(Path(path).read_text())
    return data


def score_notification(n, now):
    w = TYPE_WEIGHT.get(n.get("type"), 0)
    created = datetime.fromisoformat(n["createdAt"]) if n.get("createdAt") else now
    age_seconds = max(0, (now - created).total_seconds())
    recency_score = max(0, int(1_000_000 - age_seconds))  # simple transform
    return w * 10_000_000 + recency_score


def top_n(notifications, n=10):
    now = datetime.now(timezone.utc)
    scored = []
    for item in notifications:
        if item.get("createdAt") and item["createdAt"].endswith("Z"):
            item["createdAt"] = item["createdAt"].replace("Z", "+00:00")
        score = score_notification(item, now)
        scored.append((score, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [i[1] for i in scored[:n]]


def main():
    data_path = Path(__file__).parent / "sample_notifications.json"
    notifications = load_notifications(data_path)
    top = top_n(notifications, 10)
    out_path = Path(__file__).parent / "sample_output.txt"
    with out_path.open("w", encoding="utf-8") as f:
        for i, item in enumerate(top, 1):
            line = f"{i}. [{item['type']}] {item['createdAt']} - {item['message']} (id={item['id']})\n"
            f.write(line)
    print(f"Wrote top {len(top)} notifications to {out_path}")


if __name__ == "__main__":
    main()
