# Interfaces

## Partial inventory v0.1

Persona 1 exports `data/inventories/partial_inventory.json` for Persona 2.

Each item in `bricks` contains:

- `id`: unique brick identifier within the processed image.
- `bbox_px`: detection rectangle using the image top-left as origin.
- `center_px`: detected brick center in image pixels.
- `color_group`: currently `unknown`; later `dark`, `medium`, or `light`.
- `color_score`: currently `0.0`; later the color classification confidence.

`processing_status` is `partial` while color estimation is pending. Persona 2 can already test counting, identifiers, and planning flow, but should not yet make real blending decisions from color.
