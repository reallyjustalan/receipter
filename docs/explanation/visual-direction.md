# Deferred visual direction: the interface as a printed receipt

**Status: intentionally not implemented. Reserved for a separate future commit.**

The intended visual language comes from the output itself: dot-matrix marks, receipt typography and the dotted texture of impact printing. The interface should feel related to the paper it creates, not like a printer test bench or a generic polished dashboard.

The current functional update deliberately uses system fonts, basic borders and structural layout CSS. It establishes the three workspaces, responsive receipt canvas, reorderable list and persistent image controls without committing to a visual theme.

## Direction for a future styling commit

- Evaluate legible, appropriately licensed dot-matrix or pixel/receipt-style typefaces. Consider tabular monospaced figures for costs and restrained display lettering for headings.
- Echo the printer’s discrete dots in small separators, icons and section boundaries. Explore perforated edges and sparse paper texture without making every surface noisy.
- Limit the palette primarily to paper white, black ink and red ribbon accents.
- Base motif spacing on the receipt’s dot grid, but keep interface text readable at normal screen sizes.
- Keep labels, focus states, contrast, touch targets and error messages accessible. Dot patterns must not be the only indication of state.
- Avoid decorative CSS that obscures the live receipt or makes controls harder to use.

This future work is **presentation-only**. Fonts used in the UI must not silently replace receipt-rendering fonts, introduce extra rasterization passes, alter canonical scale or change printer bytes. Receipt typography changes, if desired, need their own output tests and explicit review.

See [rendering architecture](rendering.md) for the boundary between display styling and printer output.
