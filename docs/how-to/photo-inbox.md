# Automatically ingest JPEGs from a folder

Receipter watches a folder on the server computer; it does not communicate with the camera. For a Nikon Zf, use a compatible version of Nikon NX Tether to transfer shots into that folder.

1. Create a dedicated destination folder, e.g. `~/Pictures/Camera Inbox`, and select it in your tethering software.
2. Run Receipter using one server process: `uv run main.py`.
3. Open **Photo inbox** in the top bar.
4. Enter the folder's absolute path (or a path beginning with `~`) and click **Save settings**. **Watch for new JPEGs** and **Include JPEGs already in this folder** are preselected on first setup.
5. Close the inbox. In **Receipt layout**, the **Camera photos** tray automatically shows the latest 12 saved shots. New JPEGs appear after transfer completes, usually within a few seconds, without reopening the inbox.
6. Drag a thumbnail onto the receipt or a section to insert it before that section. Dropping on blank receipt space inserts before the footer. Or click the thumbnail’s **Add** button (also works on touch devices). You can also drop image files from Finder onto the receipt or section list.
7. For more photos, open **Photo inbox**: click **Add latest photo**, or select thumbnails and click **Add selected to receipt**. A receipt can contain up to three photos. Use the existing editor to adjust them and **Printer preview** to choose copies and explicitly print.

Existing JPEGs are included on first setup by default. Uncheck **Include JPEGs already in this folder** before saving if you want only new shots. After setup this option resets to unchecked; select it again when changing to a folder whose existing shots you want. **Import existing JPEGs** also saves your folder settings and enables watching. Duplicate content is skipped. Pasted paths may include surrounding spaces or quotes. Pause watching by unchecking the box and saving. Shots received while paused are picked up when watching resumes, including after a restart.

## Storage and limits

- Only immediate `.jpg`, `.jpeg`, `.jpe`, `.jfif`, `.jif` and `.jfi` files are scanned, case-insensitively (including `.JPG`, `.JPEG` and mixed case). Contents must decode as JPEG regardless of the extension. No subfolders, symlinks, RAW files or other formats.
- Maximum 20 MB per JPEG. The importer waits for unchanged size/mtime across two scans and decodes the JPEG before accepting it. Invalid or incomplete images are retried; an error appears in the inbox.
- Originals are copied without modification. Pillow creates a compressed JPEG working copy (quality 90, up to 4096 pixels on the longest side) for the editor, plus a 320-pixel thumbnail. Both apply EXIF orientation. High megapixel counts no longer cause an app-level rejection; Pillow’s decompression-bomb protection remains enabled. Existing saved photos get working copies on first use. The app never deletes files from the source folder or camera.
- Identical content is imported only once, even with a different filename. Changed content can be imported as a new photo.
- The SQLite catalogue, folder settings, originals, working copies and thumbnails live in `~/.receipter/inbox`. Set `RECEIPTER_DATA_DIR` before starting the server to use a different parent directory.
- Storage is persistent, with no automatic cleanup. Back up the entire storage directory together. Receipt drafts are still browser-tab-only; the catalogue does not save editable receipts or track print history yet.
- The tray displays the latest 12 photos; the inbox displays the latest 100, and **Load more** reveals older photos. The tray refreshes while the page is visible, even when the inbox is closed. Reloading repopulates it from saved photos but does not add anything to your receipt.
- Selections download compressed working copies concurrently, with loading/error feedback. A bounded in-tab cache avoids downloading the same photo repeatedly. Failed downloads leave the receipt unchanged; retry explicitly. The three-photo limit is checked again after downloads.
- Folder scanning runs every two seconds while enabled, independently of whether the inbox is open. A periodic rescan also catches files received while the server was stopped.

Nothing prints automatically. The inbox adds selected photos to the current receipt; per-photo batch printing is not implemented. [Named receipt profiles](receipt-profiles.md) save reusable logos, text and layout without saving camera photo sections.

## Troubleshooting

If no photos appear, first check that the tethering software is actually saving JPEGs to the chosen folder. Connecting the USB cable or enabling Receipter's watcher alone does not transfer images. Confirm **Watching**, check for errors, and verify macOS allows the terminal/server process to read that folder. Enter the path on the computer running Receipter, not on a separate browser device.

Changing the destination in NX Tether requires updating the folder setting in Receipter too. Keep running one server process without multiple workers.

Test without a camera: enable watching on an empty folder, then copy a JPEG into it. No printer is needed.
