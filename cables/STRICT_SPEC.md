# 🔒 STRICT MODE — MSPMetro Cables

DO NOT DEVIATE FROM THIS SPEC.

## Purpose

Implement a **Cables** section for MSPMetro that publishes **verifiable, print-resilient situational awareness documents** (“Cables”) from Markdown into synchronized artifacts.

## Core Principles (Non-Negotiable)

- Content-first, not UI-first
- No decorative borders or framing
- No rotated text
- No microtext used as a page border
- One QR/Aztec anchor only
- All documents must be reproducible from source

## File Tree (Authoritative)

```
cables/
├── content/
│   └── 2025/
│       └── 12/
│           └── 20/
│               └── mspm-cbl-2025-12-20-001.md
├── templates/
│   ├── cable.tex
│   └── cable.html
├── build/
│   ├── pdf/
│   ├── html/
│   └── feed.xml
├── tools/
│   ├── lint_cable.py
│   ├── build_cable.py
│   └── aztec.py
├── pages/
│   └── what-is-a-cable.md
└── Makefile
```

## Build Rules (Mandatory)

From one Markdown source, generate:

1. HTML page (canonical)
2. PDF cable (print artifact)
3. feed.xml entry

Additionally, generate a container page and bulk-download bundles:

- `cables/build/html/index.html` (lists multiple Cables)
- `cables/build/pdf/cables-all.zip` (bulk PDF download)
- `cables/build/html/daily-YYYY-MM-DD.html` and `cables/build/pdf/daily/YYYY-MM-DD.zip` (day bundles)

All three MUST:

- contain identical text content
- reference the same Cable ID
- expose the same SHA-256 hash

## PDF Layout Rules (Do Not Break)

PDF MUST contain, in order:

1. Cable header
2. Cable text:
   - SUMMARY
   - FACTS
   - ASSESSMENT
   - OUTLOOK
3. `START CABLE`
4. Cable text (SUMMARY..OUTLOOK)
5. `END CABLE`
6. `START VERIFICATION`
7. Condensed verification block (UTC/SHA/SIG/Canonical)
8. Aztec code centered on its own line, with Cable ID printed under it
9. `END VERIFICATION`

No rails. No borders. No rotated text. No microtext framing.

Verification block should not split across pages; if it does not fit, it moves to the next page intact.

## Feed Rules

- RSS or Atom acceptable
- `<guid>` MUST equal SHA-256
- `<description>` MUST equal SUMMARY
- `<enclosure>` MUST link to PDF

## STOP CONDITIONS

Abort the build if:

- Markdown contains raw HTML
- Any non-ASCII characters appear in cable Markdown
- Any MicroCode field is missing
- SHA-256 is malformed
- UTC timestamp is not Zulu

---

# Aztec Encoder (Required)

QR is a placeholder. Use Aztec Code.

## Payload (Canonical)

```
https://www.mspmetro.com/cables/MSPM-CBL-YYYY-MM-DD-XXX
```

Optional fragment:

```
#sha256=<first16hex>
```

## Placement

- Bottom-right of the verification paragraph
- Within verification block
- Square
- No caption except Cable ID

## Implementation

- Use a dedicated Aztec encoder library
- Embed as raster or vector
- No styling, no colors, no logos

---

# MicroCode Linter — Grammar v1 (Locked)

```
<CABLE-ID> | UTC:<ISO8601Z> | SHA256:<64HEX> | SIG:<ALG>-<KEYID>
```

Notes:

- The delimiter is ` | ` (ASCII) to satisfy the “ASCII only” requirement.
- SHA256 must be uppercase hex.
