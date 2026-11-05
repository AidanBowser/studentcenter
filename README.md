# Student Center desk

A read-only desk for the CCSU Student Center AssetPanda account. It answers three day-to-day questions:

- What is checked out, assigned, damaged, or missing right now?
- Which assets went out for an event, and were they returned?
- Who scanned or audited which items, and when?

AssetPanda is never updated from this app. The only requests are sign-in and the record search AssetPanda uses to list assets. Search does not create or change records.

## Run

```bash
python3 -m pip install -r requirements.txt
export ASSETPANDA_EMAIL="you@example.edu"
export ASSETPANDA_PASSWORD="your-password"
python3 server.py
```

Open http://127.0.0.1:8765

The first read walks every asset, because history is stored on each record. The page is usable while that read is still going, and the copy is saved in `data/asset-index.json` (gitignored) so the next start opens immediately.

Without those two variables, the page opens on a few fictional records so the layout can be checked. Those are not the Student Center account.

## How a search works

There is no event calendar in this account. A scheduled event shows up as the reason typed on **Tech check out** (for example, "Grad open house"), or as the note on a patron checkout, assignment, or equipment handoff.

A scan is an **Inventory update** or a **Mass update**. AssetPanda groups one pass into a session named with the person and the time. The desk groups those rows the same way.

Leave the box empty and you get event moves from the last 120 days, scans from the last 30 days, and the latest patron loans. Type an event, asset, or person to search the whole history. Dates narrow that search.
