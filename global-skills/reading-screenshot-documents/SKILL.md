---
name: reading-screenshot-documents
description: Use when a .odt/.docx/.pptx or PDF yields no text on extraction because its content is embedded screenshots, when recovering quiz or exam questions from LMS screen captures, or when building a reference from photographed book pages. Symptoms — text extraction returns zero paragraphs, content is only in Pictures/ or media/, dropdowns or menus obscure part of the page.
---

# Reading Screenshot-Only Documents

## Overview

A document whose content is embedded screenshots has no text layer. You must read the images — and
the moment you do, you inherit two problems that silently produce confident, wrong output:

1. **You do not know the order.** Image filenames do not encode document order.
2. **You do not know what is missing.** Screenshots crop, and open dropdowns cover the page beneath.

**Core principle: recover order from the document body, and prove completeness from the images
themselves. Never infer either from filenames or from how tidy the result looks.**

## The Order Trap

Extracting with `sorted(zipfile.namelist())` gives you **filename** order. In OOXML-family formats
(`.odt`, `.docx`, `.pptx`) image files are named by content hash or arbitrary index; the order they
appear in the body is a separate thing entirely.

Observed: an 8-image `.odt` whose filename sort was `7, 5, 3, 4, 2, 6, 8, 1` against document order.
Every question in the resulting answer key was misnumbered.

**Always parse the body for image references, in order:**

```python
import zipfile, re
z = zipfile.ZipFile(path)
xml = z.read('content.xml').decode('utf-8')      # .docx: 'word/document.xml'
hrefs = [m.group(1) for m in re.finditer(r'xlink:href="([^"]+)"', xml)]
#         .docx: r'r:embed="([^"]+)"' then resolve through word/_rels/document.xml.rels
for i, h in enumerate(hrefs, 1):
    open(f'doc{i:02d}.png', 'wb').write(z.read(h))
```

Name the extracted files by their **position**, not their source name. That way a later mistake is
visible instead of silent.

## Proving Completeness

The screenshots themselves carry the evidence. Two checks, both mechanical.

### 1. Occlusion chaining — proves adjacency

When a screenshot has an open dropdown or menu, it covers the content beneath it — but text
extending past the widget's edge is still visible. That fragment belongs to the *next* item. Read
it, and confirm it matches the next screenshot's content.

Find the text lines and which ones extend past the widget:

```python
from PIL import Image
import numpy as np
a = np.array(Image.open(f).convert('L')); dark = a < 128
rows = dark.sum(1); lines = []; run = None
for y, v in enumerate(rows):                      # group rows into text lines
    if v > 3 and run is None: run = y
    elif v <= 3 and run is not None:
        if y - run >= 5: lines.append((run, y))
        run = None
for y0, y1 in lines:                              # x-extent of each line
    cols = np.where(dark[y0:y1].any(0))[0]
    print(f"y={y0}-{y1} x={cols.min()}-{cols.max()}")
```

Lines reaching well past the widget's right edge are background — the following items. A chain
where each screenshot's background fragments match the next screenshot's foreground is **proof of
adjacency**. A break in the chain is an unverified join: say so.

### 2. Scrollbar check — proves a list isn't truncated

A dropdown showing 7 options may have 20. Before concluding the option set is complete, check the
list's right edge for a scrollbar:

```python
box = np.array(Image.open(f).convert('RGB'))[y0:y1, x0:x1]
print(np.unique(box[:, -22:].reshape(-1, 3), axis=0))
```

Highlight colour, border grey, and white only → no scrollbar → the list is complete. A distinct
grey band with a darker thumb → the list is scrolled and you are seeing a subset.

## State What You Cannot Prove

A screenshot is cropped by whoever took it. Nothing inside the file tells you whether the first
capture is the first item on the page. **Say this explicitly in the output** rather than letting a
complete-looking result imply completeness.

Likewise, a satisfying structural coincidence is not proof. "7 options and 7 blanks, so each is
used once" only holds *after* the scrollbar check and the chain check. Reaching for it first is
how a wrong answer feels right.

## Never Declare Illegible From a Downscale

A phone photograph of a book page is routinely 3000×4000 or larger. Viewing it whole means
downscaling it to something like 1100px — and at that size body text *is* unreadable. That is a
limitation you introduced, not one in the source.

**Rotate and crop at native resolution before concluding anything is illegible.**

```python
im = Image.open(path)                      # e.g. 3072x4080
up = im.rotate(90, expand=True)            # get it upright first
prev = up.copy(); prev.thumbnail((900, 900))   # preview ONLY to locate the region
s = up.width / 900.0                       # scale factor back to native
crop = up.crop((int(x0*s), int(y0*s), int(x1*s), int(y1*s)))
crop = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
```

Use the downscale to *find* the region and the native-resolution crop to *read* it. Two upscaled
crops of half a page each will resolve text that the full-page view loses entirely.

Observed: a reference document declared two pages of questions unrecoverable and asked the owner
to re-photograph them. Both read cleanly on the first native-resolution crop. The request wasted
the owner's time and would have looked like a defect in their photography.

**Also check you are on the right page.** A section that "should" close page 21 may open page 22.
Before asking for a re-shoot, look on the facing page and the next spread.

## Building a Verbatim Reference

Photographed pages are rotated, shadowed, and unevenly lit. Fidelity is not uniform across a page,
so **mark it per passage** instead of implying a uniform standard the source cannot support:

| Mark | Meaning |
|:--|:--|
| *(none)* | Verbatim — clearly legible |
| ⚠️ paraphrase | Meaning certain, wording not. Do not quote. |
| ❓ gap | Not legible. Names what to re-shoot. |

Headings, numbered lists, defined terms, figure captions, and numeric facts photograph well and are
reliably verbatim. Dense body prose often is not. A document that claims uniform verbatim fidelity
over a photographed source is making a promise the images do not support.

Always include a **page → source-image index** so any claim can be checked, and collect the ❓ gaps
into one list of what needs re-shooting.

## Quick Reference

| Step | Do | Never |
|:--|:--|:--|
| Extract | Parse body XML for refs, in order | `sorted(namelist())` |
| Name | By document position (`doc01`) | By source filename |
| Order | From `draw:frame` / `r:embed` sequence | From filenames or timestamps |
| Adjacency | Chain occluded background text | Assume consecutive files are consecutive items |
| Option lists | Pixel-check for a scrollbar | Count what's visible |
| Boundaries | State that crops can't prove first/last | Let a tidy result imply completeness |
| Quotations | Mark fidelity per passage | Claim uniform verbatim |
| Legibility | Crop at native resolution, then judge | Call it illegible from a downscaled view |
| Missing section | Check the facing page and next spread | Ask for a re-shoot of the page you guessed |

## Common Mistakes

**Sorting by filename.** The single highest-frequency error. Produces confidently misnumbered
output that looks fine.

**Treating a coincidence as verification.** A neat one-to-one mapping is a *hypothesis*; the
scrollbar and chain checks are the test.

**Silent completeness.** Producing a clean numbered list from a cropped source implies you know it's
complete. If you don't, one sentence fixes it.

**Re-extracting instead of re-checking.** When told content is missing, the instinct is to re-run
extraction. The file has not changed — check its modification time, then verify order and
completeness instead.

**Asking for a re-shoot you don't need.** The most expensive mistake here, because it spends
someone else's time on a problem you created by downscaling. Exhaust native-resolution crops and
the facing pages first; a re-shoot request should name what you already tried.
