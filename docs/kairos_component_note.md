# Kairos Component Note

## Component

- `enter_kairos_dungeon(runtime)`
- file: `game_bot/scripted/components/battle.py`

## Responsibility

This is a base component.
It is responsible only for getting the game from a recoverable top-level state into the Kairos dungeon selection page.

It does not choose giant, dragon, or other dungeon-specific battle targets.

## Current Behavior

The current flow is:

1. call `return_main_island(runtime)`
2. detect and click one of:
   - `次元之门1`
   - `次元之门2`
   - `次元之门3`
3. detect and click `连续战斗`
4. if the UI is stuck in the previous repeat-battle settlement result, handle the leftover branch
5. detect and click `连续战斗_卡伊洛斯地下城`

## Recovery Logic

This component now contains real recovery behavior, not only a happy path.

### Popup recovery

While returning to main island, popup rules from `config/popups.yaml` may be matched.
If a configured popup is detected, the runtime presses `ESC`.

### Continuous battle retry

After clicking the dimension gate:

- the component polls for `连续战斗` multiple times
- it waits briefly between polls
- if still not found, it may probe configured popups
- if needed, it clicks the dimension gate again and retries

### Repeat-battle leftover branch

If `连续战斗_再来一次` is detected after entering the continuous battle page, the component handles the leftover settlement path:

1. click `连续战斗_出售所选`
2. click `连续战斗_出售所选_确定`
3. click one of:
   - `连续战斗_出售所选_确定_是`
   - `连续战斗_出售所选_无出售项`
4. if `无出售项` was clicked, press `ESC`
5. click `连续战斗_出售所选_选择地区`
6. click `连续战斗_出售所选_无出售项`

## Real Validation

This component has already been run successfully in the live game window.
The validated end-to-end path includes:

- popup dismissal
- dimension gate retry
- continuous battle entry
- no leftover branch case
- Kairos dungeon click

The leftover settlement branch was also validated independently in the live window.

## Intended Reuse

This component should be used as the shared base for higher-level dungeon entry helpers, for example:

- `enter_giant_battle(runtime)`
- `enter_dragon_battle(runtime)`
- `enter_necro_battle(runtime)`

Those higher-level helpers should build on this component instead of re-implementing the same navigation and cleanup logic.
