# Google Stitch reference export

Imported from `stitch_dev_drop_ui_concept.zip`. The archive contains six screen HTML files and the shared `dev_drop/DESIGN.md`; it does not contain seven distinct screens. Four of the six screens include PNG captures: Nearby Devices, Send Files, Transfers, and Incoming Transfer. Settings and Device Details are provided as HTML only.

Each screen's styling and small scripts are embedded in its `code.html`. The HTML also references remote Tailwind, Google Fonts, Material Symbols, and sample Google-hosted images. These are kept as source references only: the Android app does not load them, use a WebView, or depend on those remote resources. The PNGs are design references and are not packaged as app artwork.

The Compose port follows the shared dark violet palette, rounded surfaces, compact metadata typography, spacing, and bottom-navigation treatment. Sample devices, network measurements, transfer rows, and security claims in the HTML are illustrative Stitch content; the app replaces them with truthful empty and unavailable states until a real backend provides those values.
