---
name: vintage-pulp-fantasy-style
description: "Use when writing an image-generation prompt (Midjourney, Stable Diffusion, Flux, DALL-E) for art in the style of 1980s classic fantasy oil painting, pulp illustration, or old tabletop RPG rulebook art — \"make it look like an old D&D book\", \"vintage fantasy painting\", \"pulp cover style\"."
---

# Vintage Pulp & Classic Fantasy Oil Painting Style

A prompt template for the look of late 20th-century classic fantasy art, tabletop RPG
manuals and pulp illustration: traditional oil painting, dynamic poses, dramatic lighting.

## Primary prompt

Replace `[SUBJECT AND ACTION]` and keep the rest:

```
[SUBJECT AND ACTION], in the style of a vintage 1980s fantasy oil painting, classic pulp illustration, dramatic chiaroscuro lighting, warm earthy color palette, theatrical narrative realism, highly expressive faces, dynamic staged poses, thick painterly brushstrokes, canvas texture, detailed classic RPG art style, cinematic shadows, masterpiece --v 6.0
```

`--v 6.0` is Midjourney syntax. Drop it for any other generator.

## Style keywords to mix and match

| Axis | Keywords |
| --- | --- |
| Medium | traditional oil painting, thick impasto brushstrokes, vintage illustration, classic fantasy art, tabletop RPG rulebook art |
| Lighting | dramatic chiaroscuro, intense warm highlights, deep dark shadows, cinematic lighting, theatrical contrasts |
| Color palette | warm earthy tones, deep browns, ochres, rich crimsons, amber ambient light |
| Composition & mood | exaggerated facial expressions, chaotic action, dynamic staging, theatrical realism, dense composition |

## Negative prompt (Stable Diffusion / WebUI)

```
photorealistic, 3d render, octane render, plastic, flat lighting, anime, digital painting, smooth vector, modern concept art, plain background
```

## How to apply

1. Write the subject and action concretely: who, doing what, where.
2. Fill the template. Swap in keywords from the table to steer one axis.
3. Match the target generator's syntax. Midjourney takes `--v` flags and `--no` for
   negatives; Stable Diffusion takes the negative prompt as a separate field.
4. Hand back the finished prompt in a code block, ready to paste.
