"""
Centralized paper/material size definitions for BotaPrint.

To calibrate sizes for your printer, adjust width_mm / height_mm here.
All other code reads from this file — no other constants need changing.

DEVMODE mapping:
  PaperWidth  = width_mm  * 10   (tenths of mm)
  PaperLength = height_mm * 10   (tenths of mm)
"""

SUPPORTED_LABEL_SIZES: dict[str, dict[str, int]] = {
    "30x20":  {"width_mm": 30,  "height_mm": 20},
    "43x25":  {"width_mm": 43,  "height_mm": 25},
    "58x30":  {"width_mm": 58,  "height_mm": 30},
    "58x40":  {"width_mm": 58,  "height_mm": 40},
    "58x60":  {"width_mm": 58,  "height_mm": 60},
    "75x120": {"width_mm": 75,  "height_mm": 120},
    "100x50": {"width_mm": 100, "height_mm": 50},
}

DEFAULT_LABEL_SIZE = "43x25"
