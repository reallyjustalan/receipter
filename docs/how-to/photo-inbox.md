# Automatically ingest JPEG and HEIC photos from a folder

Receipter watches a folder on the server computer; it does not communicate with the camera. For a Nikon Zf, use a compatible version of Nikon NX Tether to transfer shots into that folder.

1. Create a dedicated destination folder, e.g. `~/Pictures/Camera Inbox`, and select it in your tethering software.
2. Run Receipter using one server process: `uv run main.py`.
3. Open **Photo inbox** in the top bar.
4. Enter the folder's absolute path (or a path beginning with `~`) and click **Save settings**. **Watch for new photos (JPEG / HEIC)** and **Include photos already in this folder** are preselected on first setup.
5. Close the inbox. In **Receipt layout**, the **Camera photos** tray automatically shows the latest 12 saved shots. New JPEG and HEIC photos appear after transfer completes, usually within a few seconds, without reopening the inbox.
6. Drag a thumbnail onto the receipt or a section to insert it before that section. Dropping on blank receipt space inserts before the footer. Or click the thumbnail’s **Add** button (also works on touch devices). You can also drop image files from Finder onto the receipt or section list.
7. For more photos, open **Photo inbox**: click **Add latest photo**, or select thumbnails and click **Add selected to receipt**. A receipt can contain up to three photos. Use the existing editor to adjust them and **Printer preview** to choose copies and explicitly print.

Existing JPEG and HEIC photos are included on first setup by default. Uncheck **Include photos already in this folder** before saving if you want only new shots. After setup this option resets to unchecked; select it again when changing to a folder whose existing shots you want. **Import existing photos** also saves your folder settings and enables watching. Duplicate content is skipped. Pasted paths may include surrounding spaces or quotes. Pause watching by unchecking the box and saving. Shots received while paused are picked up when watching resumes, including after a restart.

## Storage and limits

- Only immediate `.jpg`, `.jpeg`, `.jpe`, `.jfif`, `.jif`, `.jfi`, `.heic` and `.heif` files are scanned, case-insensitively (including `.JPG`, `.JPEG` and mixed case). JPEG extensions must decode as JPEG or JPEG-based MPO (camera multi-picture/MPF metadata). MPO imports use the first/main picture for working copies and preserve the full original. A different decoded format is reported explicitly, regardless of the filename; HEIC/HEIF extensions must contain a matching HEIF image. No subfolders, symlinks, RAW files or other formats.
- Maximum 20 MB per source photo. The importer waits for unchanged size/mtime across two scans and decodes the JPEG before accepting it. Invalid or incomplete images are retried; an error appears in the inbox.
- HEIC/HEIF converts locally using `/usr/bin/sips`, built into macOS—no additional Python decoder or cloud upload. The server must run on a Mac with HEIC support. The native header query has a 10-second timeout and conversion a 30-second timeout; incomplete files retry on a later scan. Originals keep their HEIC/HEIF bytes and extension; the tray/editor receive JPEG working copies.
- Originals are copied without modification. Pillow creates a compressed JPEG working copy (quality 90, up to 4096 pixels on the longest side) for the editor, plus a 320-pixel thumbnail. Both apply EXIF orientation. High megapixel counts no longer cause an app-level rejection; Pillow’s decompression-bomb protection remains enabled. Existing saved photos get working copies on first use. The app never deletes files from the source folder or camera.
- Identical content is imported only once, even with a different filename. Changed content can be imported as a new photo.
- The SQLite catalogue, folder settings, originals, working copies and thumbnails live in `~/.receipter/inbox`. Set `RECEIPTER_DATA_DIR` before starting the server to use a different parent directory.
- Storage is persistent, with no automatic cleanup. Back up the entire storage directory together. Receipt drafts are still browser-tab-only; the catalogue does not save editable receipts or track print history yet.
- The tray displays the latest 12 photos; the inbox displays the latest 100, and **Load more** reveals older photos. The tray refreshes while the page is visible, even when the inbox is closed. Reloading repopulates it from saved photos but does not add anything to your receipt.
- Selections download compressed working copies concurrently, with loading/error feedback. A bounded in-tab cache avoids downloading the same photo repeatedly. Failed downloads leave the receipt unchanged; retry explicitly. The three-photo limit is checked again after downloads.
- Folder scanning runs every two seconds while enabled, independently of whether the inbox is open. A periodic rescan also catches files received while the server was stopped.

Nothing prints automatically. The inbox adds selected photos to the current receipt; per-photo batch printing is not implemented. [Named receipt profiles](receipt-profiles.md) save reusable logos, text and layout without saving camera photo sections.

## Troubleshooting

If no photos appear, first check that the tethering software is actually saving JPEG or HEIC/HEIF photos to the chosen folder. Connecting the USB cable or enabling Receipter's watcher alone does not transfer images. Confirm **Watching**, check for errors, and verify macOS allows the terminal/server process to read that folder. Enter the path on the computer running Receipter, not on a separate browser device.

Changing the destination in NX Tether requires updating the folder setting in Receipter too. Keep running one server process without multiple workers.

`.JPG` is supported just like `.jpg`. If it was already present when the folder was first selected, click **Import existing photos**. If an error remains, read the filename/error in the inbox: a photo over 20 MB still exceeds the source-file limit, regardless of megapixels. For HEIC conversion failures, verify the **server** is running on macOS and try opening/exporting that file in Preview. Selecting a folder does not resume a stopped printer; ingestion and printer STOP are independent.

Test without a camera: enable watching on an empty folder, then copy a JPEG into it. No printer is needed.
