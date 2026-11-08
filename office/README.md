# Optional LibreOffice add-on

PDFPad's core features never need LibreOffice. Office → PDF is enabled only
when a LibreOffice executable can be found. The application checks, in order:

1. An explicit `binary=` argument (used by tests and integrations).
2. The `PDFPAD_LIBREOFFICE` environment variable.
3. This `office/` directory, looking for `program/soffice`,
   `program/soffice.bin`, or `soffice`.
4. A system `soffice` or `libreoffice` on `PATH`.

## Layout

Extract an official LibreOffice Linux x86-64 tarball so that the `program/`
directory ends up here:

```
office/
  program/
    soffice
    soffice.bin
    ...
  share/
    ...
  LICENSE
  NOTICE
```

`office/program/soffice` must be executable.

## Example

The exact archive name depends on the pinned release used for a PDFPad build:

```bash
tar -xf LibreOffice_24.2.7_Linux_x86-64_deb.tar.gz
mv LibreOffice_24.2.7.*/program office/program
mv LibreOffice_24.2.7.*/share   office/share
cp LibreOffice_24.2.7.*/LICENSE office/LICENSE
```

For development, a system LibreOffice is detected automatically, so this folder
can stay empty.

## Runtime behaviour

- Conversion runs headless with `--headless --norestore --nodefault
  --nolockcheck --nologo --invisible`.
- A private `UserInstallation` profile is created for each operation.
- Each input is copied into a hidden temporary directory inside the output
  folder before conversion, so the original folder is never written to.
- The resulting PDF is moved into place atomically.
- A per-document timeout (default 120 seconds) and cooperative cancellation
  stop the converter and clean up temporary files.

## Licensing

LibreOffice is distributed under the MPL/LGPL. Keep the license files from the
tarball with the add-on when redistributing it. The PDFPad core application does
not bundle LibreOffice.
