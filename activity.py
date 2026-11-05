"""Turn AssetPanda asset records into desk questions.

Events are not a separate calendar. A scheduled event shows up as the reason
on a Tech Check Out, or as the note on a handoff, assignment, or patron
checkout. A scan is an Inventory Update or a mass update, stamped with who
ran it and when.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")

ASSET_GROUP = "189089"

ATTENTION = [
    "Checked Out",
    "Assigned to Student Employee",
    "Assigned to Pro Staff/Graduate Intern",
    "Assigned to Cart",
    "Awaiting Assignment",
    "Lost/Missing",
    "Damaged",
    "Damaged - Stick Drift",
    "In Repairs",
    "Available at Information Desk",
]

ATTENTION_RANK = {name: index for index, name in enumerate(ATTENTION)}

# Field keys come from the live action definitions. kind "move" is a transfer
# or checkout. kind "scan" is someone walking items. kind "update" is kept
# for search and left off the default lists.
ACTIONS: dict[int, dict[str, Any]] = {
    330696: {
        "name": "Inventory update",
        "kind": "scan",
        "when": "field_4",
        "who": "field_3",
        "place": ("field_8", "field_9"),
        "notes": "field_6",
        "fields": {
            "field_3": "Logged by",
            "field_4": "Date logged",
            "field_7": "Condition",
            "field_8": "Building",
            "field_9": "Room",
            "field_6": "Notes",
            "field_10": "Student employee",
        },
    },
    355570: {
        "name": "Mass update",
        "kind": "scan",
        "when": None,
        "who": "field_5",
        "place": ("field_9",),
        "notes": None,
        "fields": {"field_5": "User", "field_9": "Area"},
    },
    330413: {
        "name": "Tech check out",
        "kind": "move",
        "when": "field_2",
        "who": "field_3",
        "logged_by": "field_7",
        "event": "field_5",
        "place": ("field_21", "field_22"),
        "returned_at": "field_9",
        "notes": "field_8",
        "fields": {
            "field_2": "Check out",
            "field_3": "With",
            "field_5": "Reason",
            "field_7": "Logged by",
            "field_9": "Returned",
            "field_8": "Return notes",
            "field_21": "Building",
            "field_22": "Room",
        },
    },
    330699: {
        "name": "Patron check out",
        "kind": "move",
        "when": "field_1",
        "who": "field_7",
        "event": "field_5",
        "place": (),
        "returned_at": "field_8",
        "notes": "field_9",
        "patron": "field_4",
        "fields": {
            "field_1": "Out",
            "field_7": "Employee",
            "field_4": "Patron ID",
            "field_5": "Guest or reason",
            "field_8": "Returned",
            "field_9": "Returned by",
        },
    },
    348137: {
        "name": "Equipment handoff",
        "kind": "move",
        "when": None,
        "who": None,
        "event": "field_1",
        "place": (),
        "fields": {"field_3": "Employee", "field_1": "Transferring to"},
    },
    330411: {
        "name": "Assign to student",
        "kind": "move",
        "when": "field_2",
        "who": "field_1",
        "logged_by": "field_52",
        "place": (),
        "returned_at": "field_4",
        "notes": "field_53",
        "fields": {
            "field_52": "Logged by",
            "field_2": "Assigned",
            "field_1": "Student",
            "field_53": "Notes",
            "field_54": "Return logged by",
            "field_4": "Returned",
            "field_5": "Return notes",
        },
    },
    360280: {
        "name": "Assign to pro staff",
        "kind": "move",
        "when": "field_2",
        "who": "field_1",
        "logged_by": "field_52",
        "place": (),
        "returned_at": "field_4",
        "notes": "field_53",
        "fields": {
            "field_52": "Logged by",
            "field_2": "Assigned",
            "field_1": "Pro staff",
            "field_53": "Notes",
            "field_54": "Return logged by",
            "field_4": "Returned",
            "field_5": "Return notes",
        },
    },
    378249: {
        "name": "Set to vehicle",
        "kind": "move",
        "when": None,
        "who": None,
        "place": ("field_2", "field_3"),
        "event": "field_1",
        "fields": {"field_1": "Vehicle", "field_2": "Building", "field_3": "Room"},
    },
    378250: {
        "name": "Set to room",
        "kind": "move",
        "when": None,
        "who": None,
        "place": ("field_7", "field_8"),
        "fields": {
            "field_7": "Building",
            "field_8": "Room",
            "field_10": "Status",
            "field_2": "Building",
            "field_3": "Room",
        },
    },
    376560: {
        "name": "Force available",
        "kind": "update",
        "when": None,
        "who": None,
        "place": ("field_2", "field_3"),
        "fields": {"field_2": "Building", "field_3": "Room"},
    },
}


def display_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return display_value(value.get("display_name") or value.get("value") or "")
    if isinstance(value, list):
        parts = [display_value(item) for item in value]
        return ", ".join(part for part in parts if part)
    text = str(value).strip()
    if text.startswith("http") and "signature" in text:
        return ""
    return text


def parse_when(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        try:
            day = datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            return None
        return day.replace(tzinfo=EASTERN)
    text = text.replace("Z", "")
    if "." in text:
        text = text.split(".", 1)[0]
    text = text.replace("T", " ")
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc).astimezone(EASTERN)


def format_when(moment: datetime | None, date_only: bool = False) -> str:
    if moment is None:
        return ""
    label = moment.strftime("%b ") + str(moment.day) + moment.strftime(", %Y")
    if date_only:
        return label
    clock = moment.strftime("%I:%M %p").lstrip("0")
    return f"{label} {clock} ET"


def _is_date_only(value: str) -> bool:
    return len(value) == 10 and value[4] == "-" and value[7] == "-"


def _session_name(session: str) -> str:
    if " / " in session:
        return session.split(" / ", 1)[0].strip()
    return session.strip()


def _join_place(parts: list[str]) -> str:
    cleaned = []
    for part in parts:
        if part and part not in cleaned:
            cleaned.append(part)
    return " · ".join(cleaned)


def normalize_asset(obj: dict[str, Any]) -> dict[str, Any]:
    data = obj.get("data") or {}
    asset_id = display_value(data.get("field_197")) or display_value(obj.get("display_name"))
    name = display_value(data.get("field_271")) or display_value(obj.get("secondary_name"))
    asset = {
        "id": str(obj.get("id") or ""),
        "asset_id": asset_id,
        "name": name,
        "category": display_value(data.get("field_15")),
        "building": display_value(data.get("field_198")),
        "room": display_value(data.get("field_199")),
        "status": display_value(data.get("field_11")),
        "student": display_value(data.get("field_16")),
        "staff": display_value(data.get("field_298")),
        "updated_at": display_value(obj.get("updated_at")),
        "actions": [],
    }
    for raw in obj.get("action_objects") or []:
        action = _normalize_action(raw, asset)
        if action:
            asset["actions"].append(action)
    asset["actions"].sort(key=lambda item: item["when_sort"], reverse=True)
    return asset


def _normalize_action(raw: dict[str, Any], asset: dict[str, Any]) -> dict[str, Any] | None:
    try:
        action_id = int(raw.get("entity_action_id") or 0)
    except (TypeError, ValueError):
        return None
    spec = ACTIONS.get(action_id)
    if spec is None:
        spec = {
            "name": f"Action {action_id}",
            "kind": "update",
            "when": None,
            "who": None,
            "place": (),
            "fields": {},
        }
    low = raw.get("low_values") or {}
    if not isinstance(low, dict):
        low = {}
    session = display_value(low.get("grouped_action_id") or raw.get("grouped_action_id"))
    values = {key: display_value(low.get(key)) for key in spec.get("fields", {})}
    when_key = spec.get("when")
    when_raw = values.get(when_key, "") if when_key else ""
    moment = parse_when(when_raw) or parse_when(display_value(raw.get("created_at")))
    date_only = bool(when_raw) and _is_date_only(when_raw)
    who = values.get(spec.get("who") or "", "")
    if not who:
        who = _session_name(session)
    logged_by = values.get(spec.get("logged_by") or "", "")
    event = values.get(spec.get("event") or "", "")
    if action_id == 348137 and event:
        event = f"To {event}"
    place = _join_place([values.get(key, "") for key in spec.get("place", ())])
    notes = values.get(spec.get("notes") or "", "")
    returned_raw = values.get(spec.get("returned_at") or "", "")
    returned_moment = parse_when(returned_raw)
    patron = values.get(spec.get("patron") or "", "")
    labeled = {label: values[key] for key, label in spec.get("fields", {}).items() if values.get(key)}
    haystack = " ".join(
        part
        for part in [
            asset["asset_id"],
            asset["name"],
            asset["category"],
            spec["name"],
            who,
            logged_by,
            event,
            place,
            notes,
            session,
            patron,
            asset["status"],
        ]
        if part
    ).lower()
    return {
        "action_id": action_id,
        "action": spec["name"],
        "kind": spec["kind"],
        "when_sort": moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if moment else "",
        "when_label": format_when(moment, date_only=date_only) if moment else "",
        "day": moment.astimezone(EASTERN).date().isoformat() if moment else "",
        "who": who,
        "logged_by": logged_by,
        "event": event,
        "place": place,
        "notes": notes,
        "patron": patron,
        "session": session,
        "returned": bool(raw.get("returned")),
        "returned_label": format_when(returned_moment, date_only=_is_date_only(returned_raw)) if returned_moment else "",
        "fields": labeled,
        "haystack": haystack,
        "asset_id": asset["asset_id"],
        "asset_name": asset["name"],
        "asset_key": asset["id"],
        "status": asset["status"],
    }


def _tokens(query: str) -> list[str]:
    return [part.lower() for part in query.split() if part.strip()]


def _hits(haystack: str, tokens: list[str]) -> bool:
    return all(token in haystack for token in tokens)


def _in_range(day: str, start: str | None, end: str | None, allow_undated: bool) -> bool:
    if not day:
        return allow_undated and not start and not end
    if start and day < start:
        return False
    if end and day > end:
        return False
    return True


def _today() -> datetime.date:
    return datetime.now(EASTERN).date()


def desk_view(
    assets: list[dict[str, Any]],
    query: str = "",
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    text = query.strip()
    tokens = _tokens(text)
    today = _today()
    if text:
        event_start, event_end = start or None, end or None
        scan_start, scan_end = start or None, end or None
        allow_undated = not start and not end
        window_note = "Matching the full history" if allow_undated else "Matching the dates you set"
    else:
        event_start = start or (today - timedelta(days=120)).isoformat()
        event_end = end or today.isoformat()
        scan_start = start or (today - timedelta(days=30)).isoformat()
        scan_end = end or today.isoformat()
        allow_undated = False
        window_note = (
            f"Event moves since {_short_day(event_start)}. "
            f"Scans since {_short_day(scan_start)}. "
            "Type an event, asset, or person to search the whole history, including patron loans."
        )

    # Tech checkouts and staff assignments carry the event name. Patron loans
    # are a separate daily list so they do not bury those events.
    event_actions = {330413, 348137, 330411, 360280}
    moves: list[dict[str, Any]] = []
    scans: list[dict[str, Any]] = []
    patron_actions: list[dict[str, Any]] = []
    for asset in assets:
        for action in asset["actions"]:
            if action["action_id"] == 330699:
                patron_actions.append(action)
            if tokens and not _hits(action["haystack"], tokens):
                continue
            if action["kind"] == "move" and _in_range(action["day"], event_start, event_end, allow_undated):
                if not text and action["action_id"] not in event_actions:
                    continue
                moves.append(_public_action(action))
            elif action["kind"] == "scan" and _in_range(action["day"], scan_start, scan_end, allow_undated):
                scans.append(action)
            elif text and action["kind"] == "update" and _in_range(action["day"], event_start, event_end, allow_undated):
                moves.append(_public_action(action))

    moves.sort(key=lambda item: item["when_sort"], reverse=True)
    patron_actions.sort(key=lambda item: item["when_sort"], reverse=True)
    today_iso = today.isoformat()
    patron_today = sum(1 for action in patron_actions if action["day"] == today_iso)
    latest_patrons = [] if text else [_public_action(action) for action in patron_actions[:12]]
    sessions = _sessions(scans)[:40]
    status_counts = Counter(asset["status"] or "Blank" for asset in assets)
    out_now = [asset for asset in assets if asset["status"] in ATTENTION]
    out_now.sort(key=lambda asset: (ATTENTION_RANK.get(asset["status"], 99), asset["asset_id"]))
    matching = []
    if tokens:
        matching = [asset for asset in assets if _hits(_asset_haystack(asset), tokens)]
        matching.sort(key=lambda asset: asset["asset_id"])

    return {
        "query": text,
        "hint": window_note,
        "counts": [{"name": name, "count": count} for name, count in status_counts.most_common()],
        "summary": {**_summary(assets, moves, scans), "patron_today": patron_today},
        "out_now": [_public_asset(asset) for asset in out_now[:80]],
        "events": moves[:80],
        "patrons": latest_patrons,
        "scans": sessions,
        "assets": [_public_asset(asset) for asset in matching[:40]],
    }


def _summary(assets: list[dict[str, Any]], moves: list[dict[str, Any]], scans: list[dict[str, Any]]) -> dict[str, int]:
    assigned = sum(1 for asset in assets if asset["status"].startswith("Assigned"))
    trouble = sum(
        1
        for asset in assets
        if asset["status"] in {"Damaged", "Damaged - Stick Drift", "Lost/Missing", "In Repairs"}
    )
    checked_out = sum(1 for asset in assets if asset["status"] == "Checked Out")
    return {
        "assets": len(assets),
        "checked_out": checked_out,
        "assigned": assigned,
        "trouble": trouble,
        "moves": len(moves),
        "scans": len(scans),
    }


def _sessions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for action in actions:
        key = action["session"] or f"{action['who']}|{action['when_sort']}|{action['asset_key']}"
        grouped.setdefault(key, []).append(action)
    sessions = []
    for key, items in grouped.items():
        items.sort(key=lambda item: item["when_sort"])
        places = [item["place"] for item in items if item["place"]]
        conditions = [item["fields"].get("Condition") or item["fields"].get("Area") or "" for item in items]
        conditions = [item for item in conditions if item]
        who = _session_name(items[0]["session"]) or items[0]["who"]
        if "@" in who and items[0]["who"] and "@" not in items[0]["who"]:
            who = items[0]["who"]
        sessions.append(
            {
                "id": key,
                "who": who or items[0]["logged_by"],
                "logged_by": items[0]["logged_by"] or items[0]["who"],
                "when_label": items[0]["when_label"],
                "when_sort": items[0]["when_sort"],
                "place": Counter(places).most_common(1)[0][0] if places else "",
                "condition": Counter(conditions).most_common(1)[0][0] if conditions else "",
                "count": len(items),
                "action": items[0]["action"],
                "assets": [
                    {
                        "asset_id": item["asset_id"],
                        "asset_name": item["asset_name"],
                        "condition": item["fields"].get("Condition", ""),
                        "place": item["place"],
                    }
                    for item in items
                ],
            }
        )
    sessions.sort(key=lambda item: item["when_sort"], reverse=True)
    return sessions


LOAN_ACTIONS = {330413, 330699, 330411, 360280}


def _clip(text: str, limit: int = 140) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _public_action(action: dict[str, Any]) -> dict[str, Any]:
    if action["event"]:
        reason = _clip(action["event"])
    elif action["action_id"] in {330411, 360280} and action["notes"]:
        reason = _clip(action["notes"])
    else:
        reason = action["action"]
    if action["action_id"] not in LOAN_ACTIONS:
        back = ""
    elif action["returned_label"]:
        back = action["returned_label"]
    elif action["returned"]:
        back = "Returned"
    else:
        back = "Still out"
    return {
        "when_label": action["when_label"],
        "when_sort": action["when_sort"],
        "asset_id": action["asset_id"],
        "asset_name": action["asset_name"],
        "action": action["action"],
        "reason": reason,
        "who": action["who"],
        "logged_by": action["logged_by"],
        "place": action["place"],
        "returned": action["returned"],
        "returned_label": back,
        "notes": action["notes"],
        "patron": action["patron"],
        "status": action["status"],
    }


def _public_asset(asset: dict[str, Any]) -> dict[str, Any]:
    who = asset["student"] or asset["staff"]
    return {
        "asset_id": asset["asset_id"],
        "name": asset["name"],
        "category": asset["category"],
        "status": asset["status"],
        "who": who,
        "place": _join_place([asset["building"], asset["room"]]),
    }


def _asset_haystack(asset: dict[str, Any]) -> str:
    return " ".join(
        part
        for part in [
            asset["asset_id"],
            asset["name"],
            asset["category"],
            asset["status"],
            asset["student"],
            asset["staff"],
            asset["building"],
            asset["room"],
        ]
        if part
    ).lower()


def _short_day(iso_day: str) -> str:
    moment = datetime.strptime(iso_day, "%Y-%m-%d").replace(tzinfo=EASTERN)
    return format_when(moment, date_only=True)


def sample_assets() -> list[dict[str, Any]]:
    """A small fictional desk so the page can open with no account configured."""
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    older = (now - timedelta(days=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
    scan_day = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    session = "Riley Chen / " + (now - timedelta(days=1)).astimezone(EASTERN).strftime("%m/%d/%Y %I:%M %p").lower()
    return [
        normalize_asset(
            {
                "id": "sample-tech",
                "display_name": "TECH100",
                "data": {
                    "field_197": "TECH100",
                    "field_271": "Projector",
                    "field_15": {"value": "Tech"},
                    "field_198": {"value": "Student Center"},
                    "field_199": {"value": "Ballroom"},
                    "field_11": {"value": "Checked Out"},
                },
                "action_objects": [
                    {
                        "entity_action_id": 330413,
                        "created_at": older,
                        "returned": False,
                        "low_values": {
                            "field_2": older.replace("T", " ").replace("Z", ""),
                            "field_3": "Jordan Hale",
                            "field_5": "Grad Open House",
                            "field_7": "riley.chen@example.edu",
                            "field_21": "Student Center",
                            "field_22": "Ballroom",
                        },
                    }
                ],
            }
        ),
        normalize_asset(
            {
                "id": "sample-radio",
                "display_name": "RADIO100",
                "data": {
                    "field_197": "RADIO100",
                    "field_271": "Radio",
                    "field_15": {"value": "Radio"},
                    "field_198": {"value": "Student Center"},
                    "field_199": {"value": "Accountability"},
                    "field_11": {"value": "Available"},
                },
                "action_objects": [
                    {
                        "entity_action_id": 330696,
                        "created_at": recent,
                        "returned": False,
                        "low_values": {
                            "field_4": scan_day,
                            "field_3": "riley.chen@example.edu",
                            "field_7": "available",
                            "field_8": "Student Center",
                            "field_9": "Accountability",
                            "grouped_action_id": session,
                        },
                    }
                ],
            }
        ),
        normalize_asset(
            {
                "id": "sample-radio-2",
                "display_name": "RADIO101",
                "data": {
                    "field_197": "RADIO101",
                    "field_271": "Radio",
                    "field_15": {"value": "Radio"},
                    "field_198": {"value": "Student Center"},
                    "field_199": {"value": "Accountability"},
                    "field_11": {"value": "Damaged"},
                },
                "action_objects": [
                    {
                        "entity_action_id": 330696,
                        "created_at": recent,
                        "returned": False,
                        "low_values": {
                            "field_4": scan_day,
                            "field_3": "riley.chen@example.edu",
                            "field_7": "damaged",
                            "field_8": "Student Center",
                            "field_9": "Accountability",
                            "grouped_action_id": session,
                        },
                    }
                ],
            }
        ),
    ]
