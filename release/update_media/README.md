## Update Media Staging

Put release-note images for the next update in this folder while preparing the release.

Recommended files:

- `hero.png`
- `files_to_cards.png`
- `study_improvements.png`

Recommended size:

- 1400px to 1800px wide
- PNG or JPG
- clean 16:9 or close to it

## Where These Show Up

The in-app update dialog reads the GitHub release body and can show up to 3 images under the update notes.

To make that work:

1. Upload the images somewhere publicly reachable, such as GitHub release assets or raw GitHub-hosted images.
2. Paste those image URLs into the GitHub release body using Markdown image syntax:

```md
![Files To Cards](https://your-image-url/files_to_cards.png)
![Study Improvements](https://your-image-url/study_improvements.png)
```

## Suggested Content

- One image showing the new Files To Cards flow
- One image showing the study-area improvements
- One image showing any onboarding or setup simplification
