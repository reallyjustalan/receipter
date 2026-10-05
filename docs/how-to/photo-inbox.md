# Automatically ingest JPEGs from a folder

Receipter watches a folder on the server computer; it does not communicate with the camera. For a Nikon Zf, use a compatible version of Nikon NX Tether to transfer shots into that folder.

1. Create a dedicated destination folder, e.g. `~/Pictures/Camera Inbox`, and select it in your tethering software.
2. Run Receipter using one server process: `uv run main.py`.
3. Open **Photo inbox** in the top bar.
4. Enter the folder's absolute path (or a path beginning with `~`), enable **Watch for new JPEGs**, and click **Save settings**.
5. Take a photo. Its JPEG appears automatically after transfer completes, usually within a few seconds.
6. Select thumbnails and click **Add selected to receipt**. A receipt can contain up to three photos. Use the existing editor to adjust them and **Printer preview** to choose copies and explicitly print.

Files already present when a new folder is selected are not imported automatically. Click **Import existing JPEGs** to include those files. Watching must be enabled for this import. Pause watching by unchecking the box and saving. Shots received while paused are picked up when watching resumes, including after a restart.

## Storage and limits

- Only immediate `.jpg` / `.jpeg` files are scanned, case-insensitively. No subfolders, symlinks, RAW files or other formats.
- Maximum 20 MB per JPEG. The importer waits for unchanged size/mtime across two scans and decodes the JPEG before accepting it. Invalid or incomplete images are retried; an error appears in the inbox.
- Originals are copied without modification. Thumbnails apply EXIF orientation. The app never deletes files from the source folder or camera.
- Identical content is imported only once, even with a different filename. Changed content can be imported as a new photo.
- The SQLite catalogue, folder settings, originals and thumbnails live in `~/.receipter/inbox`. Set `RECEIPTER_DATA_DIR` before starting the server to use a different parent directory.
- Storage is persistent, with no automatic cleanup. Back up the entire storage directory together. Receipt drafts are still browser-tab-only; the catalogue does not save editable receipts or track print history yet.
- The inbox displays the latest 100 photos; **Load more** reveals older photos.
- Folder scanning runs every two seconds while enabled, independently of whether the inbox is open. A periodic rescan also catches files received while the server was stopped.

Nothing prints automatically. The inbox adds selected photos to the current receipt; per-photo batch printing and saved receipt templates are not implemented.

## Troubleshooting

If no photos appear, first check that the tethering software is actually saving JPEGs to the chosen folder. Connecting the USB cable or enabling Receipter's watcher alone does not transfer images. Confirm **Watching**, check for errors, and verify macOS allows the terminal/server process to read that folder. Enter the path on the computer running Receipter, not on a separate browser device.

Changing the destination in NX Tether requires updating the folder setting in Receipter too. Keep running one server process without multiple workers.

Test without a camera: enable watching on an empty folder, then copy a JPEG into it. No printer is needed.
