import json
import os
import threading
import unittest
from datetime import timedelta
from datetime import datetime
from datetime import timezone
from urllib.request import Request, urlopen

from activity import desk_view, sample_assets
from assetpanda import ReadOnlyError, assert_read_only
from server import DESK, make_server


FORBIDDEN = [
    ("POST", "/v3/groups/189089/objects"),
    ("POST", "/v3/groups/189089/objects/archive"),
    ("POST", "/v3/groups/189089/objects/unarchive"),
    ("PUT", "/v3/groups/189089/objects"),
    ("PATCH", "/v3/groups/189089/objects/abc"),
    ("DELETE", "/v3/attachments"),
    ("POST", "/v3/users"),
    ("PUT", "/v3/users/1"),
    ("POST", "/v3/reports"),
    ("GET", "/v3/reports/1"),
    ("PUT", "/v3/reports/1"),
    ("DELETE", "/v3/reports/1"),
    ("POST", "/v3/groups/189089/actions"),
    ("POST", "/v3/groups/abc/search/objects"),
    ("POST", "/v3/groups/189089/search/objects/extra"),
    ("GET", "https://evil.example/v3/groups"),
    ("POST", "/v3/groups/189089/search/objects?limit=1"),
]

ALLOWED = [
    ("GET", "/v3/groups"),
    ("GET", "/v3/groups/189089/fields"),
    ("GET", "/v3/users/me"),
    ("GET", "/v3/entity_objects/abc/change_logs"),
    ("GET", "/v3/entity_objects/abc/action_objects"),
    ("POST", "/v3/session/token"),
    ("POST", "/v3/groups/189089/search/objects"),
]


class ReadOnlyTests(unittest.TestCase):
    def test_blocks_writes(self):
        for method, path in FORBIDDEN:
            with self.subTest(method=method, path=path):
                with self.assertRaises(ReadOnlyError):
                    assert_read_only(method, path)

    def test_allows_reads_and_sign_in(self):
        for method, path in ALLOWED:
            with self.subTest(method=method, path=path):
                assert_read_only(method, path)

    def test_search_rejects_anything_but_a_query(self):
        from assetpanda import AssetPanda

        client = AssetPanda("desk@example.edu", "not-used", http=lambda *args, **kwargs: None)
        with self.assertRaises(ReadOnlyError):
            client.search_objects("189089", {"objects": [{"field_1": "changed"}]})
        with self.assertRaises(ReadOnlyError):
            client.search_objects("../v3/users", {})


class DeskTests(unittest.TestCase):
    def setUp(self):
        self.assets = sample_assets()

    def test_event_search_finds_the_checkout_reason(self):
        view = desk_view(self.assets, "grad open house")
        self.assertEqual(len(view["events"]), 1)
        event = view["events"][0]
        self.assertEqual(event["asset_id"], "TECH100")
        self.assertEqual(event["reason"], "Grad Open House")
        self.assertEqual(event["who"], "Jordan Hale")
        self.assertEqual(event["place"], "Student Center · Ballroom")
        self.assertEqual(event["returned_label"], "Still out")

    def test_unrelated_event_is_not_a_match(self):
        view = desk_view(self.assets, "career fair")
        self.assertEqual(view["events"], [])
        self.assertEqual(view["scans"], [])

    def test_scans_group_by_person_and_pass(self):
        view = desk_view(self.assets)
        self.assertEqual(len(view["scans"]), 1)
        session = view["scans"][0]
        self.assertEqual(session["who"], "Riley Chen")
        self.assertEqual(session["count"], 2)
        self.assertEqual(
            {item["asset_id"] for item in session["assets"]},
            {"RADIO100", "RADIO101"},
        )

    def test_still_out_uses_current_status(self):
        view = desk_view(self.assets)
        ids = [asset["asset_id"] for asset in view["out_now"]]
        self.assertEqual(ids, ["TECH100", "RADIO101"])

    def test_patron_loans_do_not_bury_events(self):
        from activity import normalize_asset

        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        patron = normalize_asset(
            {
                "id": "sample-patron",
                "display_name": "RADIO200",
                "data": {
                    "field_197": "RADIO200",
                    "field_271": "Radio",
                    "field_11": {"value": "Available"},
                },
                "action_objects": [
                    {
                        "entity_action_id": 330699,
                        "created_at": stamp,
                        "returned": False,
                        "low_values": {
                            "field_1": stamp.replace("T", " ").replace("Z", ""),
                            "field_7": "Desk Worker",
                            "field_4": "3001001",
                            "field_5": "club fair",
                        },
                    }
                ],
            }
        )
        assigned = normalize_asset(
            {
                "id": "sample-assign",
                "display_name": "TECH200",
                "data": {
                    "field_197": "TECH200",
                    "field_271": "Speaker",
                    "field_11": {"value": "Available"},
                },
                "action_objects": [
                    {
                        "entity_action_id": 330411,
                        "created_at": stamp,
                        "returned": True,
                        "low_values": {
                            "field_2": stamp.replace("T", " ").replace("Z", ""),
                            "field_1": "Jordan Hale",
                            "field_53": "event tech - philbrick camp",
                        },
                    }
                ],
            }
        )
        assets = self.assets + [patron, assigned]
        default = desk_view(assets)
        self.assertFalse(any(item["action"] == "Patron check out" for item in default["events"]))
        self.assertEqual(default["patrons"][0]["reason"], "club fair")
        self.assertEqual(default["summary"]["patron_today"], 1)
        found = desk_view(assets, "philbrick")
        self.assertEqual(found["events"][0]["reason"], "event tech - philbrick camp")
        self.assertEqual(found["events"][0]["asset_id"], "TECH200")
        loans = desk_view(assets, "club fair")
        self.assertEqual(loans["events"][0]["action"], "Patron check out")

    def test_old_window_hides_the_recent_event(self):
        start = (datetime.now(timezone.utc) - timedelta(days=40)).date().isoformat()
        end = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
        view = desk_view(self.assets, "grad open house", start, end)
        self.assertEqual(view["events"], [])

    def test_signature_urls_are_dropped(self):
        asset = {
            "id": "x",
            "display_name": "TECH1",
            "data": {"field_197": "TECH1", "field_271": "Mic", "field_11": {"value": "Available"}},
            "action_objects": [
                {
                    "entity_action_id": 330413,
                    "created_at": "2026-03-01T16:16:54.592Z",
                    "returned": True,
                    "low_values": {
                        "field_2": "2026-03-01 16:16:54",
                        "field_3": "Ada",
                        "field_5": "concert",
                        "field_6": "https://panda-assets-live.s3.amazonaws.com/uploads/signatures/abc",
                        "field_9": "2026-03-02 12:00:00",
                    },
                }
            ],
        }
        from activity import normalize_asset

        action = normalize_asset(asset)["actions"][0]
        self.assertNotIn("http", json.dumps(action["fields"]))
        self.assertEqual(action["event"], "concert")
        self.assertTrue(action["returned_label"] or action["returned"])


class ServerTests(unittest.TestCase):
    def setUp(self):
        os.environ["ASSETPANDA_SAMPLE"] = "1"
        os.environ.pop("ASSETPANDA_EMAIL", None)
        os.environ.pop("ASSETPANDA_PASSWORD", None)
        DESK.load()
        self.server = make_server("127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_page_and_event_search(self):
        page = urlopen(self.base).read().decode()
        self.assertIn("What went out for an event", page)
        body = json.load(urlopen(self.base + "/api/desk?q=grad+open+house"))
        self.assertTrue(body["read_only"])
        self.assertEqual(body["source"], "sample")
        self.assertEqual(body["events"][0]["reason"], "Grad Open House")
        request = Request(self.base + "/api/refresh", method="POST", data=b"")
        refreshed = json.load(urlopen(request))
        self.assertTrue(refreshed["read_only"])


if __name__ == "__main__":
    unittest.main()
