# Skin Competition — Design Spec
**Date:** 2026-03-16
**Status:** Approved

## Overview

Add a skin competition feature to SkinCoach: users compete for the highest skin score, verified via a daily challenge code (anti-cheat), with separate leaderboards for natural skin and with makeup.

---

## 1. Skin Score

Computed by the vision model at every photo submission.

### Step 2 vision prompt JSON output contract

The existing `2_vision.txt` prompt currently outputs a 5-component skin_score with field names `tone/hydration/texture/radiance/cleanliness` (each 0–20). This implementation replaces that schema with 7 components. The `radiance` field is renamed to `vitality`. Two new fields (`youth`, `eye_area`) are added. Downstream prompts (steps 3–8) that use `vis["skin_score"]` will continue to receive a `skin_score.total` field and are not otherwise sensitive to component names.

New JSON output required from step 2 vision model:
```json
{
  "skin_score": {
    "tone": 12,
    "hydration": 13,
    "texture": 11,
    "vitality": 10,
    "cleanliness": 13,
    "youth": 12,
    "eye_area": 3,
    "total": 74
  },
  "has_makeup": false,
  "visual_age": 28
}
```

### Components (total 100 points)

| Field | Description | Max |
|---|---|---|
| `tone` | Tone uniformity — absence of spots, redness | 15 |
| `hydration` | Hydration — no dryness, flaking | 15 |
| `texture` | Texture smoothness — pores, scars, unevenness | 15 |
| `vitality` | Vitality — healthy colour vs dull/grey look | 15 |
| `cleanliness` | Cleanliness — absence of blemishes, inflammation | 15 |
| `youth` | Youth — how young the skin looks visually | 15 |
| `eye_area` | Eye area — bags, dark circles, puffiness | 10 |

`total` = sum of all 7 components (max 100).

### Additional fields (informational, not scored)
- `has_makeup: bool` — whether visible makeup is detected by vision model. If model is uncertain, defaults to `false`. No user correction mechanism in v1 (accept LLM decision as-is).
- `visual_age: int` — estimated visual age of skin. Displayed in personal analysis output only. Not used in scoring.

`has_makeup` and `visual_age` must **always** be populated in vision output, regardless of the `healthy` flag. If `healthy=false` (bad photo quality) and `skin_score` is null, `on_compete_photo` must reject the submission and reply: _"Фото не подходит для оценки. Попробуй ещё раз с хорошим освещением."_ (does not consume a retry attempt).

### Score storage per user

New fields added to user data in `history.json`. Defaults added in `ensure_fields`:
```json
{
  "skin_score_last": null,
  "skin_score_components": null,
  "skin_score_history": [],
  "best_score_natural": null,
  "best_score_makeup": null,
  "compete_date": null,
  "challenge_code": null,
  "challenge_date": null,
  "compete_retry_count": 0
}
```

Score history entry format:
```json
{"date": "2026-03-16", "score": 74, "has_makeup": false, "verified": true, "components": {"tone": 12, ...}}
```

History is capped at last 30 entries. Regular (non-compete) photos also append to `skin_score_history` with `"verified": false`. Leaderboard queries filter to `verified: true` only.

---

## 2. Competition Flow (Hybrid Architecture)

### Regular photo (no /compete)
- Skin score is computed and shown to the user privately in the analysis reply
- Score appended to `skin_score_history` with `verified: false`
- `skin_score_last` and `skin_score_components` updated
- Score is NOT counted in leaderboard

### Competition photo (/compete command)
1. User calls `/compete`
2. **Already competed today (UTC):** bot replies with their today's score and rank; no new code issued
3. **Has not competed today:** bot generates a fresh 4-digit challenge code, stores `challenge_code` + `challenge_date` (UTC date string `YYYY-MM-DD`), sets state to `S_COMPETE`, sets `compete_retry_count = 0`
4. Bot sends: _"Для рейтинга напиши на бумажке: **4823** и сфотографируй кожу рядом с ней 📸"_
5. User sends photo → `handle_photo` detects `S_COMPETE` state
6. **Liveness check** (separate API call, `max_tokens=100`, before full pipeline):
   - Prompt: "Is the handwritten number {code} visible on paper or a hand in this photo? Reply JSON only: {\"code_visible\": true/false}"
   - `code_visible: false`:
     - Increment `compete_retry_count`
     - If `compete_retry_count >= 3`: reset state to `S_ACTIVE`, reply: _"Превышен лимит попыток. Попробуй /compete завтра."_
     - Else: reply _"Код не найден. Убедись что цифры **{code}** видны на бумаге рядом с кожей. Попытка {n}/3."_ Stay in `S_COMPETE`
   - `code_visible: true`: proceed
7. Full pipeline runs (steps 1–8) normally to generate analysis
8. `on_compete_photo(u, score_components, has_makeup)` called in `gamification.py` to store result. `on_compete_photo` calls `get_weekly_key()` internally — the caller (`bot.py`) does NOT pass week_key.
9. State returns to `S_ACTIVE`

### Date arithmetic
All date comparisons use **UTC** throughout. `challenge_date` and `compete_date` stored as ISO date strings computed from `datetime.utcnow().date().isoformat()`.

`gamification.py`'s existing `_today()` uses `date.today()` (local time). `can_compete_today()` and `get_weekly_key()` must NOT use `_today()` — they must use `datetime.utcnow()` directly. Additionally, `_today()` itself should be updated to `datetime.utcnow().date().isoformat()` as part of this change to make all streak/activity tracking consistent (low-risk change, same behaviour in UTC deployments like Railway).

---

## 3. Anti-Cheat: Liveness Verification

The challenge code approach prevents:
- Using old photos from camera roll
- Using other people's photos
- Resubmitting the same photo

**Liveness check call:**
- Separate vision API call using `VISION_M` model, `max_tokens=100`
- Prompt (inline, not from a `.txt` file): `"Is the handwritten number {code} visible on paper or a hand in this photo? Reply JSON only: {\"code_visible\": true/false}"`
- Expected response: `{"code_visible": true}` or `{"code_visible": false}`
- Parsed with existing `xj()` helper; if parsing fails → treat as `code_visible: false`
- **Max retries:** 3 attempts per day. After 3 failures, state resets to `S_ACTIVE` and user must try again next day.
- No fuzzy matching: any response other than `{"code_visible": true}` is treated as failure

---

## 4. Leaderboard

### Existing `/leaderboard` — unchanged
Keeps current behaviour: top-10 by streak + gamification points. `format_leaderboard(all_users)` signature unchanged.

### New command: `/skinrank`

Calls new function `format_skinrank(all_users, viewer_uid)` (not `format_leaderboard`).

Displays four sections:
1. **Without makeup — this week** (Mon–Sun UTC, ISO week)
2. **Without makeup — all time**
3. **With makeup — this week**
4. **With makeup — all time**

Weekly key: `datetime.utcnow().strftime("%G-W%V")` (ISO 8601 week, e.g. `"2026-W11"`). Week membership of a score entry determined by converting stored `date` field to ISO week at query time.

Tie-breaking: same score → earlier submission date wins (lower `date` string).

Format:
```
🏆 РЕЙТИНГ КОЖИ

─── БЕЗ МАКИЯЖА ───────────────
Эта неделя:
🥇 Анна — 87
🥈 Максим — 82
🥉 Дарья — 79

Всё время:
🥇 Олег — 94
🥈 Анна — 91
...

─── С МАКИЯЖЕМ ──────────────────
Эта неделя:
🥇 Вика — 95
...

───────────────────────────────
Твой лучший: 74 (без макияжа) | 88 (с макияжем)
📸 /compete — участвовать сегодня
👉 /leaderboard — рейтинг по очкам и стрику
```

If viewer has no competition history: footer shows _"Ты ещё не участвовал — попробуй /compete!"_

### Leaderboard rules
- Only `verified: true` scores count
- Best score per user per week (not average)
- Top 10 per category
- Names shown as entered by user at onboarding

---

## 5. State Machine Update

Current states: `name → dur → tried → photo → questions → active → labs`

New state:
- `S_COMPETE = "compete"` — waiting for competition photo with challenge code

**`handle_text` behaviour in `S_COMPETE` state:**
Reply: _"Жду фото с кодом **{code}** на бумажке. Отправь фото или напиши /start чтобы выйти."_
Do NOT fall through to any other branch. State remains `S_COMPETE`.

After photo processed (success or any terminal failure) → state returns to `S_ACTIVE`.

---

## 6. Implementation: Files to Change

### `gamification.py`
- Add new fields to `ensure_fields` defaults (see Section 1 storage schema)
- Add `on_compete_photo(u, score_components, has_makeup)` → calls `get_weekly_key()` internally, stores verified entry, updates `best_score_natural` / `best_score_makeup`, caps `skin_score_history` at 30
- Add `on_regular_photo_score(u, score_components, has_makeup)` → stores unverified entry, updates `skin_score_last` + `skin_score_components`
- Add `can_compete_today(u)` → `bool` (compares `compete_date` to today UTC)
- Add `get_weekly_key()` → `str`, e.g. `"2026-W11"` using UTC
- Add `format_skinrank(all_users, viewer_uid)` → `str` (new function, does NOT change `format_leaderboard`)

### `bot.py`
- Add `S_COMPETE = "compete"` constant
- Add `cmd_compete` handler: check `can_compete_today`, generate/show code, set state
- In `handle_text`: add `S_COMPETE` branch (see Section 5 above)
- In `handle_photo`:
  - Call `on_regular_photo_score` after step 2 for all photos (updates `skin_score_last`)
  - If state is `S_COMPETE`: run liveness check before pipeline; handle retries; on success call `on_compete_photo`
  - Append `skin_score` breakdown to every photo analysis reply
- Add `cmd_skinrank` handler calling `format_skinrank(h, uid)`
- Register `/compete` and `/skinrank` in `set_my_commands` in `post_init`
- `/leaderboard` and `format_leaderboard` remain unchanged

### `2_vision.txt` prompt
- Update to output new 7-component `skin_score` JSON schema (replacing existing 5-component schema)
- `radiance` renamed to `vitality`, `youth` and `eye_area` added
- Add `has_makeup` and `visual_age` fields to output (required even when `healthy=false`)

### `3_reasoning.txt` prompt
- Update `skin_score` echo template: rename `radiance` → `vitality`, add `youth` and `eye_area` fields
- Update max annotations (20 → 15 for most fields, 10 for `eye_area`)
- Grade thresholds (85–100 / 70–84 / 50–69 / 0–49) remain valid (total still 0–100)

### `8_response.txt` prompt
- Update skin score display line: replace `Сияние: {skin_score.radiance}/20` with `Живость: {skin_score.vitality}/15`
- Add display for `youth` and `eye_area` components
- Update max values from `/20` to `/15` (or `/10` for `eye_area`)

### `competition.py` (new helper module)
- `generate_challenge_code() -> str` — returns 4-digit random string
- `check_liveness(b64_image, expected_code) -> bool` — calls vision API inline prompt, returns bool

---

## 7. Constraints

- Railway free tier ~512MB RAM. Regular photos: skin score computed inside existing step 2 call (no extra API call). Competition photos: one extra lightweight vision call (liveness check, `max_tokens=100`) before the normal pipeline.
- Score history capped at 30 entries per user.
- Challenge code stored as plaintext in `history.json` — acceptable for MVP, low-severity risk.
