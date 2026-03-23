Packaged update media lives here.

Structure:

- `assets/updates/common/`
  - generic pre-install update prompt content
- `assets/updates/<version>/`
  - first-launch "what's new" content for that installed version

Recommended version folder example:

- `assets/updates/1.0.0-beta.5/`

Files the app looks for:

- `manifest.json`
- `update_prompt_banner_16x9.png`
- `whats_new_top_banner_16x9.png`
- `whats_new_showcase_16x9.png`
- `whats_new_closing_banner_16x9.png`

Notes:

- The pre-install dialog uses packaged content from `common` in the currently installed app.
- The first-launch "what's new" dialog uses packaged content from the new installed version folder.
- If an image is missing, ONCard will show a clean placeholder banner instead of crashing.
