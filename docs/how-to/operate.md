# How to run, test and troubleshoot

## Start or update the app

```sh
uv sync
uv run main.py
```

Open <http://localhost:8022>. Use a single process, without multiple workers: STOP and preview snapshots are process-local. To use another port, run `PORT=8023 uv run main.py`.

After changing source files, stop and restart the server, then refresh the browser. UI assets are deliberately frozen at startup, so live file edits cannot expose controls against an older backend. Export anything needed before refreshing; drafts are not persisted. A stale browser is blocked from printing.

## Run tests without paper

```sh
uv run python -m unittest discover -s tests -v
node tests/test_editor.js
node tests/test_output_log.js
uv run playwright install chromium
uv run python tests/browser_smoke.py
```

Python tests cover rendering, SVG resource rejection, crop/processing, reorder invariants, totals, canonical scale, API snapshots and the retained transport/STOP guarantees. Node tests cover pure editor helpers, local date formatting, hex formatting and stale output-response handling. The Playwright test starts a temporary server, uses actual rendering endpoints, mocks status/print delivery, checks desktop/mobile interactions and asserts zoom causes no rendering request. It saves screenshots under `/tmp/receipter-*.png` and a temporary server log under `/tmp/receipter-browser-server.log`.

## Stop unexpected printing

Click **STOP**, press **Esc**, or run:

```sh
curl -X POST http://localhost:8022/api/interrupt
```

Switch the printer **OFF** if buffered data continues printing. STOP only cancels unsent host data; an active USB write can take up to five seconds to return. Power on without holding FEED to clear the command parser. Only then use **Resume**, or:

```sh
curl -X POST http://localhost:8022/api/resume
```

STOP also latches after short writes/timeouts. It cannot stop other applications’ jobs and resets on server restart. Never assume an error means no paper was printed; inspect the printer before another attempt.

## Resolve a blocked Print button

Read the reason under the **Print** button:

- Connect/power on the printer for disconnection. Editing still works offline.
- Refresh the browser for build mismatch.
- Wait for the latest preview and matching encoded output; fix validation errors or choose **Refresh preview** if either stalls. The floating output panel reports preparation, submission and USB acceptance separately; it does not imply that prepared bytes have been sent.
- Shorten images/text/spacing for a receipt over 1024 rows.
- Enter 8–20 trailing feed lines with cut, or 0–20 without.
- Choose an integer copy count from 1 to 10. After a failed batch, inspect and count the actual receipts before choosing how many to print next; partial delivery is not automatically retried.
- Wait for an active job, or STOP it if necessary.
- Power-cycle then Resume after STOP.
- Refresh the preview after a print attempt, token expiry or cache eviction. Do this deliberately, not as an automatic resend after an error.

## Diagnose garbled image output

1. STOP and power-cycle first; printer-font characters between bitmap bands may indicate lost command framing.
2. Confirm the browser and server build IDs match. Inspect the logged job ID, byte count, SHA-256, part count and cut suffix.
3. If necessary, explicitly send one of the [diagnostic endpoints](../reference/printer.md), beginning with plain text. These endpoints consume paper; they are not part of the normal editing workflow.
4. Do not add automatic retries, resets or tiny-byte pacing to the normal receipt path. Delivery uncertainty is a reason to stop, not repeat the job.
5. Physically inspect the receipt and cutter. USB acceptance alone does not verify readable graphics or a completed cut.

The historical source of intermittent corruption is not established. Complete-band writes preserve framing at host transfer boundaries, but this is not proof against device data loss.

## Configure USB identifiers

Set the environment variables listed in the [printer reference](../reference/printer.md) before startup. The backend expects an already configured device on interface 0 and deliberately avoids reset/SET_CONFIGURATION. Do not run another print application against the same USB device while testing.
