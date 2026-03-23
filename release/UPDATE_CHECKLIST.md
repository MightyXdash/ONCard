## ONCards Update Checklist

1. Sync local `main` with `origin/main` before packaging a release.
2. Bump the app version in `src/studymate/version.py`.
3. Build the Windows installer with a filename that starts with `ONCards-Setup`.
4. Create a GitHub release with a newer tag than the installed version, for example `v1.0.0-beta.5`.
5. Upload the installer `.exe` to that GitHub release.
6. Write release notes in the GitHub release body.
7. If you want images in the in-app update dialog, include up to 3 image URLs in the release body.
8. Keep user data safe:
   - ONCards stores app data in `%APPDATA%\\ONCards` and `%LOCALAPPDATA%\\ONCards`
   - replacing the installed app should not delete user databases unless the installer explicitly removes those folders
9. Test the update flow on a machine with an older installed version:
   - launch the older app
   - wait for the update prompt
   - download the installer
   - close ONCards
   - confirm the installer launches
   - confirm cards/profile/history are still present after install

## Current Updater Expectations

- Latest release is read from GitHub Releases API.
- The updater compares semantic versions from the GitHub tag.
- The installer asset must be a `.exe`.
- The installer asset name should include `ONCards-Setup`.
- Update-note images come from URLs inside the GitHub release body, not from local packaged assets.
