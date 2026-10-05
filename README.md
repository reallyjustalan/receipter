# Receipter

A local photo-booth receipt builder for the Epson TM-U220: SVG logos, up to three independently edited photos, itemised costs, text and signatures in reorderable sections.

On macOS, install the native USB library first (also needed on a new laptop):

```sh
brew install libusb uv
uv sync
uv run main.py
```

Open <http://localhost:8022>. Run **one server process**, without multiple workers. Nothing prints automatically. Drafts live in the browser tab; download the receipt PNG before leaving. Editable project persistence is not implemented.

## Documentation — Diátaxis

- **Tutorial:** [Make your first photo receipt](docs/tutorials/first-receipt.md)
- **How-to guides:** [Automatically ingest JPEGs](docs/how-to/photo-inbox.md) · [Edit a receipt](docs/how-to/edit-receipts.md) · [Run, test and troubleshoot](docs/how-to/operate.md)
- **Reference:** [Receipt model and API](docs/reference/receipt-api.md) · [Printer and diagnostic endpoints](docs/reference/printer.md)
- **Explanation:** [Canonical rendering and preview architecture](docs/explanation/rendering.md) · [Receipt typography and font fidelity](docs/explanation/receipt-typography.md)

The current minimal UI is intentional; no visual redesign is planned.

## Safety

**STOP / Esc** cancels unsent data. Power off the printer to stop data already buffered inside it; power-cycle before Resume. USB acceptance is not confirmation of readable output or a completed cut. No automatic retries or queued jobs.

## Tests

```sh
uv run python -m unittest discover -s tests -v
node tests/test_editor.js
node tests/test_output_log.js
uv run playwright install chromium
uv run python tests/browser_smoke.py
uv run python tests/browser_inbox.py
```

Tests do not print. The browser test starts its own isolated server and mocks printer status and print delivery.
