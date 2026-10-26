# CS2 Tab source snapshot — 2026-10-25

Selected resources were **read-only copied** from the owner's installed CS2
VPK to `cs2_tab_reference_20261025` outside the game and repository. Only those
copies were passed to Source2Viewer. No game launch, process access, injection,
debugger, plug-in, game-file write, or Steam interaction was used. The client
loads only the versioned PNG/OTF/TTF pack, never the installation directory.
These precautions describe our actions, not a guarantee about Valve policies.

Owner explicitly authorized redistribution of these assets earlier in this
chat. Original game resources remain Valve's; this is not a claim of ownership
or an upstream open-source license.

## Source-to-renderer mapping

`rm_client/ui/cs2_scoreboard.py` transcribes the **classic competitive / with
timeline / no half-times** variant of the copied XML, using its set-0 row:

| Original selector/snippet | Transcribed value |
| --- | --- |
| `.sb-main` | centered, Y +30, padding top/left/right 20, radius 5, black 0.88 |
| `csgostyles.css` `backgroundDotsSize` | 360×360, image opacity 0.015 |
| `color-CT` / `color-T` | #B5D4EE / #EAD18A |
| `.sb-meta` | 75px, 24px mode icon, 22px bold-condensed mode/map, 18px clock, 14px right-aligned server |
| `left-panel-width` / `sb-row-width` / `sb-row-width-inner` | 80 / 830 / 770px |
| classic CT / T team snippets | blue above gold; large left score rail, one shared column header |
| `.sb-team__info__score Label` | 70px Stratum2 Mono Bold |
| `row-image-size`, `.sb-row` | 24px cells + 1px top/bottom margins |
| competitive set-0 | status, ping, flair, avatar, name, money, K, D, A, HSP, damage |
| ping / money / HSP / damage widths | 37 / 66 / 64 / 50px; name fills remaining width |
| row fonts | Stratum2 Medium names, Regular Mono stats, Regular Condensed headers |
| `.sb-row--localplayer` | blue/gold 0.07 wash; no invented accent stripe |
| dead rows | #999 wash, transparent cell backgrounds, original skull material |
| `.sb-row__cell` | 250ms CSS ease-out wash; premultiplied row-texture interpolation |
| `.sb-timeline__segments` / `.sb-timeline` | 100px middle strip + 2px top/bottom margin; 650px round region |
| `.sb-row--transition` | 250ms CSS ease-in-out row sorting, reversible from the current position |
| `anim-pulse` | known numeric changes brighten glyphs 1→3 at 5%→1, one second; no opaque flash |
| `.sortstat` | #FFFFFF10 cell background and brighter text |
| `.highlight-row:hover` | rgba(200,200,200,0.05) |
| `.sb-footer-panel` | 48px, original 24px caster-control slots/16px image area |

## Deliberate RM adaptations / evidence limits

- Blue/red RM teams replace CT/T; source colors and component geometry remain.
  RM role/ID/portraits replace Steam player identities; HSP becomes **HP**.
- Missing/stale/unverified referee values are `—`. This does not manufacture
  deaths, assists, damage, ping, money, or a working 2027 protocol.
- RM has no CS rounds. The source competitive timeline now remains in the
  component tree. Its ticks are elapsed match time, and its two bands show
  **observed alive→zero-HP losses**. No bombs, winners, MVPs or loss bonuses are
  invented. History is bounded and reset by source/session/round identity;
  stale/unknown HP cannot establish an edge. These are observations, not
  complete match statistics or kill attributions.
- RM tactical map docks **outside** the centered source panel on the left.
  Both use the existing reversible Tab/map reveal. That group reveal is an RM
  adaptation: the CSS's **1s width/height transition is not an opening fade**.
  Native engine visibility timing cannot be inferred from that declaration.
- Steam voice/caster/X-ray/report/commend are not implemented in RM. Footer
  reference icons are dimmed and disabled, not fake
  buttons issuing commands. All board input is consumed before combat input.
- This is a native Qt transcription, not the Panorama engine. It is not
  certified pixel-identical on an in-game screenshot or identical in all
  engine-owned animations. Offscreen checks do not certify GPU FPS.

## Export audit

`provenance.json` locks the original compiled-resource hashes, exported-file
hashes and retained resource-block hashes. Source2Viewer 20.0 cannot parse new
RED2 editor KV3 metadata. **Only analysis copies** omit RED2. Before bundling,
`tools/import_cs2_scoreboard_reference.py` verifies every remaining block
byte-for-byte against the untouched originals (including DATA/SrMa/LaCo).
Font extraction also runs only against the copied `stratum2.uifont`.
The first failed decompile was not treated as success; exported files and
content blocks are checked explicitly. TS/XML are evidence, not runtime code.

The normal competitive, signal-strength, stats and elimination SVGs were also
copied and block-verified in the independent analysis area. Multicolour images
use RGB multiplication (Panorama wash), not an alpha-only replacement fill.
All Stratum2 styles share a family name, so exact style names must be selected;
registering the font file alone does not select its bold/condensed face.
