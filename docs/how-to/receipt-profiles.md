# Save reusable receipt defaults

Profiles keep your logo, text and layout on the server so they survive page reloads and app restarts.

1. Build your default receipt: upload a logo, edit the heading/subheading, footer items and message, text sections, signature label and image adjustments.
2. Optionally set **Use current date & time**, **Use photo count as quantity** on footer items, copies, cut and trailing feed lines.
3. Open **Profiles** in the top bar.
4. Choose **New profile**, enter a name and leave **Load this profile by default when opening Receipter** checked if it should be your startup template.
5. Click **Save current defaults**. Wait for **Saved on this server**.

Camera photo sections are deliberately excluded, even if your receipt contains shots when you save. Automatic photo-quantity modes are preserved; they count each new receipt's body photos rather than capturing the current count. Logos, other sections and their order are preserved. Automatic-date settings are preserved, but their captured timestamps are cleared and refreshed when the template loads. Manually entered dates/references are saved literally—clear them first if they are specific to one customer.

## Update or switch profiles

- To update one, choose its name in **Saved profile**, then **Save current defaults**. This overwrites that profile with the current editor's defaults; selecting a name alone does not load it.
- To start from a saved template, choose its name and click **Load selected profile**. Confirm replacement: this removes the current draft's edits and camera photos. Download anything needed first.
- To create another template without overwriting the selected one, click **New profile** and enter another name.
- Only one profile is the server's startup default. Saving another with the default checkbox checked switches it. Unchecking it while saving the existing default clears the startup default, so new pages use the built-in receipt.

Saving is explicit, not automatic. Existing tabs keep their current receipt; they do not change when another tab saves a default. Loading a profile regenerates the preview but never prints. Wait for printing/background processing to finish before saving or loading.

## Storage and portability

Profiles (including logo bytes) live in `~/.receipter/profiles/profiles.sqlite3`, or `$RECEIPTER_DATA_DIR/profiles/profiles.sqlite3` when configured. Names, documents, options and logos are saved in a single SQLite transaction. Back up/copy the profiles directory with the app stopped to move defaults to another Mac. The photo inbox is stored separately under the same parent data directory.

Logos retain their uploaded bytes, including SVGs. If you saved a background-removed logo, the processed logo is retained; its pre-removal undo history is not saved. Camera shots, undo history, view zoom, STOP state and printer hardware settings are not part of a profile. This is reusable default persistence, not full customer-receipt project storage.
