# Beeny Panel 3.7.1 — security maintenance review

نسخه ۳.۷.۱ برای بازبینی و سخت‌سازی امنیتی آماده شده است. اسکن ClamAV روی سورس موردی گزارش نکرده؛ این نتیجه به معنی تأیید سلامت توسط Defender یا اثبات تشخیص اشتباه نسخه قبل نیست. قبل از استخراج یا نصب، فایل جدید را با Defender به‌روز اسکن کنید. اگر هشدار داد، نصب نکنید و برای فایل استثنا نسازید.

## Trigger and conclusion

Windows Defender reported `Trojan:Win32/MalUri.A!cl` inside the 3.7.0 source ZIP,
including two JavaScript files and two HTML templates. This report is taken
seriously. The precise signature trigger has **not** been established, and the
report has **not** been confirmed to be a false positive. No Microsoft sample
submission or Defender re-scan has been performed by the release author.

A local static review found no identified malicious payload in the reported
files. The reported scripts matched the preceding 3.6.9 release byte for byte;
that comparison establishes provenance within these releases, not safety.
The HTML differences were branding/cache-version changes and tunnel download
links. The ZIP contained no PE/ELF executable, Windows executable or PowerShell
file, duplicate archive member, absolute path or parent-directory traversal.

## Substantive changes

* AJAX no longer copies and executes inline JavaScript from response HTML.
* Response page programs must match a fixed same-origin local script path and
  the exact SHA-256 Subresource Integrity pin shipped in this release.
* Inline response event handlers, executable URL schemes, iframe/object/embed,
  base, meta and srcdoc are removed during the administrative page mount.
  This is a defensive mount boundary, not a claim of complete HTML sanitization.
* Users/dashboard behavior now lives in readable static JavaScript. Runtime
  values remain escaped inert JSON produced with Jinja `tojson`.
* The prebuilt React/OGL background bundle has been retired. Native WebGL uses
  the existing shader source and palette, with reduced-motion/mobile fallback.
  It performs no network request or string evaluation. The updater backs up
  the retired assets and restores them if the application upgrade rolls back.
* There are no changes to VPN ciphers, TLS options, MTU, routing, session
  enforcement, traffic accounting or the OpenVPN runtime manager in this patch.

Run `python3 scripts/build_script_pins.py` after deliberately editing a page
program, then rerun the consistency and browser tests. Pins prevent unexpected
program bytes; they are not an antivirus certification or a substitute for
reviewing intentional source changes.

## Validation and limits

ClamAV 1.5.3, official digitally verified databases, daily database version
28158 (19 October 2026 06:26 UTC), 3,628,169 known signatures:

* The original 3.7.0 ZIP scan reported zero infected files.
* The revised source scan reported zero infected files.
* The final 3.7.1 ZIP is separately scanned after packaging; the release result
  is recorded in the delivery message. No scan exclusions or disabled
  signatures are used. No file was uploaded to an external scanning service.

A clean ClamAV scan does **not** clear a Microsoft Defender detection or prove
that software contains no vulnerabilities. Windows Defender is unavailable in
this build environment. Have an updated Defender scan this exact new archive
before extracting or deploying it. If it is flagged, retain the detection
name/details and do not allow-list or disable protection to install it.

Browser validation uses a local test application and mocked service operations:
EN/FA, light/dark, mobile layouts, desktop native WebGL, AJAX without navigation,
user list reinitialization after HTML replacement, injected inline/event/URL
programs remaining inert, unapproved script not requested, and an approved-path
modified program rejected by the browser's integrity verification.

The full Python test result and exact archive scan result are recorded during
release packaging. Functional tests are separate from malware scanning.
No live VPS deployment, provider firewall test or live OpenVPN kernel tunnel
was performed for this maintenance release. Existing 3.7.0 feature limitations
in GUIDE-3.7.0-FA.md continue to apply.

## Installation

After your updated Defender accepts the file, extract on the server and run
`sudo bash scripts/update_panel.sh` from the extracted source directory for an
existing compatible installation. For a fresh VPS use `sudo bash install.sh`.
This archive has not been published to GitHub; `--github` will only retrieve it
after you publish the reviewed source. Do not use a panel Reset to update.
