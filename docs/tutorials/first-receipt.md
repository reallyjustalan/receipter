# Tutorial: make your first photo receipt

You will assemble a logo, three photos, an itemised footer and a signing area. You need two or three small images, optionally a self-contained SVG logo, and the app running at <http://localhost:8022>. A printer is not needed for editing.

1. Open **Receipt layout**. The initial receipt contains a header, an itemised footer and a signature area. The middle canvas shows the complete receipt from top to bottom.
2. Select **Header & logo**. Change the heading to “OUR DAY OUT”. Click **Upload SVG or image** and choose your logo. It appears above the heading. Leave **Fit entire image** selected to preserve the whole logo.
3. Click **Photos** and choose two or three images. The photos appear before the footer. Select a photo in the section list or on the receipt.
4. Click **Crop & process image**. The enlarged processed section is on the left; its controls remain on the right. The small full-receipt preview shows your edit in context.
5. Raise **Crop zoom** slightly. Drag the image or adjust the position sliders. Adjust brightness and contrast, and try turning dithering off and on. These settings belong only to this photo.
6. Return to **Receipt layout**. Move a photo up using its arrow. Its crop and processing move with it. You can also drag sections in the list.
7. Select **Itemised footer**. Rename the item to “Photo strip”, set quantity to 2 and unit price to 1.50. The total becomes 3.00, both in the inspector and on the receipt. Add a reference if you like. Enable **Use current date & time** to insert a local timestamp such as `08/09/2026 14:35`.
8. Select **Signature** and change its label to “We were here”. The blank area above the line is for signing on paper.
9. Change **View** to 65% or 125%. Only the displayed size changes; the receipt’s printer dots stay the same.
10. Open **Printer preview**. Review the complete receipt. The bottom **ESC/POS bytes** panel shows the prepared output; `Prepared — not sent` confirms you have not submitted it. Download the PNG if you are working without a printer. The exported PNG is the canonical dot map enlarged 2× in both axes, not an editable project.
11. If a printer is connected and ready, leave **Copies** at 1, with the default eight trailing feed lines and partial cut selected, then click **Print one receipt**. Check the physical paper. A successful USB transfer does not verify the output.

You have created a receipt from independent sections, rather than choosing a fixed layout. To start another print job, explicitly **Refresh preview** first. For several copies in one job, see [Print multiple copies](../how-to/edit-receipts.md#print-multiple-copies).

Next: [editing tasks](../how-to/edit-receipts.md) or [why preview zoom is separate from rendering](../explanation/rendering.md).
