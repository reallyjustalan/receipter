# Continuous booth printing with the saved queue

1. Prepare a receipt and choose copies, feed and cut in **Printer preview**.
2. Click **Add to queue**, enter a guest label, and wait for the saved confirmation. This is the durable save point; unsaved editor drafts still live only in the browser tab.
3. Switch to **04 Queue**, then **Start / continue queue**. This full-page print desk shows saved receipt cards, larger previews, delivery states and confirmation/reprint controls. **View full receipt** expands a saved proof. The editor and raw-byte footer are hidden here, but STOP / Esc stays available.
4. Use **Back to receipt** or an editing tab to keep importing/editing while printing runs on the server. Switching views preserves the current draft and never pauses, starts or resends a job.
5. **New receipt** clears camera photo sections but keeps logo, text and other sections. Review guest-specific text. Editing never changes previously saved queue entries.
6. Inspect every copy and cut. **Confirm & next** moves the current entry to confirmed history and permits the next waiting entry to send if the queue is running. USB acceptance alone does not advance the queue.

## Reprints and interruptions

**Reprint / remaining copies** asks how many copies to send (1–10). It pauses the queue: explicitly **Start / continue** after checking the printer. Reprinting confirmed history creates a new waiting entry without changing history. Neither successful delivery nor failure deletes a receipt.

**Pause after current transfer** finishes the current host transfer but prevents the next job. **STOP / Esc** cancels unsent data and pauses the queue. Power off to stop printer-buffered data; power-cycle before **Resume**. Resume only clears the printer STOP latch, not the queue pause. Inspect output, choose reprint or confirm, then explicitly continue.

**Delete permanently** is the only deletion action and asks for confirmation. Deleting a waiting entry skips it; deleting an uncertain entry discards its recovery data. You cannot delete, confirm or reprint an entry while it is sending. There is no automatic cleanup or automatic retry.

## Local persistence and restart

Default database: `~/.receipter/queue/queue.sqlite3` on the Mac running the server. `RECEIPTER_DATA_DIR` overrides `~/.receipter`; use the same directory after restart. The Queue tab's **Local storage** details display the actual path.

SQLite transactions commit the preview PNG, copy settings and exact single-copy ESC/POS parts together. FULL synchronous commits and macOS fullfsync are enabled. Stored band boundaries are preserved; reprinting does not re-render artwork or require source photos, browser storage, or temporary preview tokens. Saved receipts are frozen print artifacts, not editable drafts.

Browser refresh: the queue remains on the server and the worker continues. Server restart: all entries remain, the queue starts paused, and any entry previously sending becomes **interrupted / check output**. It is never automatically resent. A response lost during enqueue can be retried with the same request ID without duplicate entries.

Run one server process, without multiple workers. Storage failure prevents a successful save acknowledgment. Local persistence is not a backup: disk loss, manual file deletion or hardware failure can still lose data. For backup, stop the server and copy the queue folder to another disk. The database contains guest receipt imagery; keep it private and delete deliberately when appropriate. History has no automatic expiry and will consume disk space.
