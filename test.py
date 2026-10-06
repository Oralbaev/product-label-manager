import win32print

PRINTER_NAME = "Xprinter XP-365B"

DM_PAPERSIZE = 0x00000002
DM_PAPERLENGTH = 0x00000004
DM_PAPERWIDTH = 0x00000008
DM_ORIENTATION = 0x00000001

DMPAPER_USER = 256
DMORIENT_PORTRAIT = 1

LABEL_WIDTH_MM = 43
LABEL_HEIGHT_MM = 30

def main():
    hprinter = win32print.OpenPrinter(PRINTER_NAME)
    try:
        props = win32print.GetPrinter(hprinter, 2)
        devmode = props["pDevMode"]

        print("Before:")
        print("PaperSize:", devmode.PaperSize)
        print("PaperWidth:", devmode.PaperWidth)
        print("PaperLength:", devmode.PaperLength)
        print("Orientation:", devmode.Orientation)

        devmode.Fields |= (
            DM_PAPERSIZE
            | DM_PAPERWIDTH
            | DM_PAPERLENGTH
            | DM_ORIENTATION
        )

        devmode.PaperSize = DMPAPER_USER
        devmode.PaperWidth = LABEL_WIDTH_MM * 10    # 43.0 mm
        devmode.PaperLength = LABEL_HEIGHT_MM * 10  # 25.0 mm
        devmode.Orientation = DMORIENT_PORTRAIT

        result = win32print.DocumentProperties(
            None,
            hprinter,
            PRINTER_NAME,
            devmode,
            devmode,
            0x00000002 | 0x00000008,  # DM_IN_BUFFER | DM_OUT_BUFFER
        )

        print("\nDocumentProperties result:", result)

        print("\nAfter:")
        print("PaperSize:", devmode.PaperSize)
        print("PaperWidth:", devmode.PaperWidth)
        print("PaperLength:", devmode.PaperLength)
        print("Orientation:", devmode.Orientation)

        accepted = (
            devmode.PaperSize == DMPAPER_USER
            and devmode.PaperWidth == LABEL_WIDTH_MM * 10
            and devmode.PaperLength == LABEL_HEIGHT_MM * 10
        )

        print("\nAccepted by driver:", accepted)

    finally:
        win32print.ClosePrinter(hprinter)

if __name__ == "__main__":
    main()