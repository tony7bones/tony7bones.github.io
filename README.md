# Tony.7.Bones Kodi Repository

Kodi add-on repository hosted via GitHub Pages.

**Repository URL:** `https://tony7bones.github.io/repo`

## Add to Kodi

1. In Kodi, go to **Settings → File Manager → Add Source**
2. Enter `https://tony7bones.github.io/repo`
3. Install the repository add-on from **Add-ons → Install from zip file**

## Structure

```
repo/                  Kodi plugins (each subdir with addon.xml → zip + addons.xml)
repo/repositories/     Repository installer zips (manual install only)
repo/media/            Images browsable from Kodi file manager
_tools/                Generator script run by CI
```

## Adding content

**New plugin:** Create `repo/<addon-id>/addon.xml` and push — CI zips it and updates `addons.xml`.

**New repository zip:** Drop the `.zip` into `repo/repositories/` and push.

**New image:** Drop the image into `repo/media/` and push — CI regenerates the index.
