# Avatar System

## Goal

Build an owned avatar system that Qantara can commercialize without depending on proprietary runtimes or third-party avatar platforms.

## Phase 1 Choice

Qantara Phase 1 uses a 2D parts-based avatar system.

Reasons:

- easier to own end to end
- easier to customize in-product
- easier to support anime, cartoon, and action-figure styles
- faster to ship than a full 3D pipeline
- better fit for a browser-first product surface

## Layering

The avatar system has 3 layers:

1. Avatar pack
- static assets grouped by style family
- reusable parts such as hair, eyes, nose, mouth, brows, accessories, and outfit accents

2. Avatar descriptor
- a JSON document that selects which parts and colors make up one avatar
- the descriptor is the source of truth for user customization

3. Avatar renderer
- browser-side presentation layer
- consumes descriptor + lipsync/timing/state events
- does not own gateway logic

## Style Families

Phase 1 should support curated pack families:

- `anime_soft`
- `anime_sharp`
- `cartoon_playful`
- `action_figure`

Each family should share the same structural slot model so the editor and renderer stay stable.

## Standard Part Slots

Phase 1 slot model:

- `face_base`
- `hair_front`
- `hair_back`
- `brows`
- `eyes`
- `nose`
- `mouth_set`
- `ears`
- `accessory_head`
- `accessory_face`
- `outfit_accent`

## Customization Scope

Phase 1 customization should be constrained and composable.

Users should be able to change:

- hair
- eyes
- eyebrows
- nose
- mouth set
- skin tone
- primary colors
- accessories

Users should not need freehand drawing in Phase 1.

## Renderer Contract

The renderer should only depend on:

- avatar descriptor
- avatar pack assets
- state events: `idle`, `listening`, `thinking`, `speaking`, `interrupted`
- lipsync timeline events

The renderer should not need:

- raw audio transport frames
- backend model details
- agent tool state

## What To Avoid

- Live2D or equivalent as the core stack
- vendor-hosted avatar systems
- mixing gateway code with avatar asset logic
- hardcoding one-off avatar presets without descriptor backing

## Later

Later phases may add:

- richer expressions
- gesture layers
- imported 3D renderer path
- export/share of avatar descriptors
