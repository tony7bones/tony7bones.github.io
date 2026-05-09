import os
import urllib.request
import zipfile

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

REPO_BASE = "https://tony7bones.github.io/repo/repositories/"

REPOS = [
    "repository.kodinerds-7.0.1.7.zip",
    "repository.kodifitzwell-0.0.1.zip",
    "repository.bugatsinho-2.8.zip",
    "repository.loop-3.0.4.zip",
]

ADDONS = [
    ("skin.estuary.modv2", "Estuary MOD V2 Omega"),
    ("plugin.video.pov", "POV"),
    ("plugin.video.sporthdme", "SportsHD"),
    ("plugin.video.the-loop", "The Loop"),
    ("pvr.iptvsimple", "IPTV Simple Client"),
]

IPTV_INSTANCE_XML = """\
<settings version="2">
    <setting id="kodi_addon_instance_name">The Loop</setting>
    <setting id="kodi_addon_instance_enabled" default="true">true</setting>
    <setting id="m3uPathType" default="true">1</setting>
    <setting id="m3uPath" default="true" />
    <setting id="m3uUrl">https://bit.ly/4oo63xG</setting>
    <setting id="m3uCache" default="true">true</setting>
    <setting id="startNum" default="true">1</setting>
    <setting id="numberByOrder" default="true">false</setting>
    <setting id="m3uRefreshMode" default="true">2</setting>
    <setting id="m3uRefreshIntervalMins" default="true">60</setting>
    <setting id="m3uRefreshHour" default="true">10</setting>
    <setting id="connectioncheckinterval" default="true">10</setting>
    <setting id="connectionchecktimeout" default="true">20</setting>
    <setting id="defaultProviderName" default="true" />
    <setting id="enableProviderMappings" default="true">false</setting>
    <setting id="providerMappingFile" default="true">special://userdata/addon_data/pvr.iptvsimple/providers/providerMappings.xml</setting>
    <setting id="tvGroupMode" default="true">0</setting>
    <setting id="numTvGroups" default="true">1</setting>
    <setting id="oneTvGroup" default="true" />
    <setting id="twoTvGroup" default="true" />
    <setting id="threeTvGroup" default="true" />
    <setting id="fourTvGroup" default="true" />
    <setting id="fiveTvGroup" default="true" />
    <setting id="customTvGroupsFile" default="true">special://userdata/addon_data/pvr.iptvsimple/channelGroups/customTVGroups-example.xml</setting>
    <setting id="tvChannelGroupsOnly" default="true">false</setting>
    <setting id="radioGroupMode" default="true">0</setting>
    <setting id="numRadioGroups" default="true">1</setting>
    <setting id="oneRadioGroup" default="true" />
    <setting id="twoRadioGroup" default="true" />
    <setting id="threeRadioGroup" default="true" />
    <setting id="fourRadioGroup" default="true" />
    <setting id="fiveRadioGroup" default="true" />
    <setting id="customRadioGroupsFile" default="true">special://userdata/addon_data/pvr.iptvsimple/channelGroups/customRadioGroups-example.xml</setting>
    <setting id="radioChannelGroupsOnly" default="true">false</setting>
    <setting id="epgPathType" default="true">1</setting>
    <setting id="epgPath" default="true" />
    <setting id="epgUrl">https://cutt.ly/Le1JrbXW</setting>
    <setting id="epgCache" default="true">true</setting>
    <setting id="epgTimeShift" default="true">0</setting>
    <setting id="epgTSOverride" default="true">false</setting>
    <setting id="epgIgnoreCaseForChannelIds" default="true">true</setting>
    <setting id="useEpgGenreText" default="true">false</setting>
    <setting id="genresPathType" default="true">0</setting>
    <setting id="genresPath" default="true">special://userdata/addon_data/pvr.iptvsimple/genres/genreTextMappings/genres.xml</setting>
    <setting id="genresUrl" default="true" />
    <setting id="logoPathType" default="true">1</setting>
    <setting id="logoPath" default="true" />
    <setting id="logoBaseUrl" default="true" />
    <setting id="useLogosLocalPathOnly" default="true">false</setting>
    <setting id="logoFromEpg" default="true">1</setting>
    <setting id="mediaEnabled" default="true">true</setting>
    <setting id="mediaGroupByTitle" default="true">true</setting>
    <setting id="mediaGroupBySeason" default="true">true</setting>
    <setting id="mediaTitleSeasonEpisode" default="true">false</setting>
    <setting id="mediaM3UGroupPath" default="true">0</setting>
    <setting id="mediaForcePlaylist" default="true">false</setting>
    <setting id="mediaVODAsRecordings" default="true">true</setting>
    <setting id="timeshiftEnabled" default="true">false</setting>
    <setting id="timeshiftEnabledAll" default="true">true</setting>
    <setting id="timeshiftEnabledHttp" default="true">true</setting>
    <setting id="timeshiftEnabledUdp" default="true">true</setting>
    <setting id="timeshiftEnabledCustom" default="true">false</setting>
    <setting id="catchupEnabled" default="true">false</setting>
    <setting id="catchupQueryFormat" default="true" />
    <setting id="catchupDays" default="true">5</setting>
    <setting id="allChannelsCatchupMode" default="true">0</setting>
    <setting id="catchupOverrideMode" default="true">0</setting>
    <setting id="catchupCorrection" default="true">0</setting>
    <setting id="catchupPlayEpgAsLive" default="true">false</setting>
    <setting id="catchupWatchEpgBeginBufferMins" default="true">5</setting>
    <setting id="catchupWatchEpgEndBufferMins" default="true">15</setting>
    <setting id="catchupOnlyOnFinishedProgrammes" default="true">false</setting>
    <setting id="transformMulticastStreamUrls" default="true">false</setting>
    <setting id="udpxyHost" default="true">127.0.0.1</setting>
    <setting id="udpxyPort" default="true">4022</setting>
    <setting id="useFFmpegReconnect" default="true">true</setting>
    <setting id="useInputstreamAdaptiveforHls" default="true">false</setting>
    <setting id="defaultUserAgent" default="true" />
    <setting id="defaultInputstream" default="true" />
    <setting id="defaultMimeType" default="true" />
</settings>"""


def _is_installed(addon_id):
    try:
        xbmcaddon.Addon(addon_id)
        return True
    except RuntimeError:
        return False


def _install_repo(zip_name, dialog, pct):
    dialog.update(pct, f"Installing repository: {zip_name}")
    temp_path = xbmcvfs.translatePath("special://temp/" + zip_name)
    addons_path = xbmcvfs.translatePath("special://home/addons/")
    try:
        urllib.request.urlretrieve(REPO_BASE + zip_name, temp_path)
        with zipfile.ZipFile(temp_path, "r") as z:
            z.extractall(addons_path)
    except Exception as e:
        xbmc.log(
            f"[tony7bones.bootstrap] Failed to install {zip_name}: {e}", xbmc.LOGERROR
        )
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _install_addon(addon_id, name, dialog, pct):
    dialog.update(pct, f"Installing: {name}")
    if _is_installed(addon_id):
        xbmc.log(f"[tony7bones.bootstrap] {addon_id} already installed, skipping")
        return
    xbmc.executebuiltin(f"InstallAddon({addon_id})", True)
    xbmc.sleep(2000)


def _configure_iptv(dialog, pct):
    dialog.update(pct, "Configuring IPTV Simple Client...")
    data_dir = xbmcvfs.translatePath("special://userdata/addon_data/pvr.iptvsimple/")
    xbmcvfs.mkdirs(data_dir)
    settings_path = os.path.join(data_dir, "instance-settings-1.xml")
    with open(settings_path, "w", encoding="utf-8") as f:
        f.write(IPTV_INSTANCE_XML)
    xbmc.sleep(500)


def run():
    dialog = xbmcgui.DialogProgress()
    dialog.create("Tony 7 Bones Setup", "Starting setup...")

    total = (
        len(REPOS) + 1 + len(ADDONS) + 1
    )  # repos + repo-update + addons + iptv-config
    step = 0

    for zip_name in REPOS:
        step += 1
        _install_repo(zip_name, dialog, int(step / total * 100))
        xbmc.sleep(500)
        if dialog.iscanceled():
            dialog.close()
            return

    step += 1
    dialog.update(int(step / total * 100), "Updating repository index...")
    xbmc.executebuiltin("UpdateAddonRepos()", True)
    xbmc.sleep(3000)
    if dialog.iscanceled():
        dialog.close()
        return

    for addon_id, name in ADDONS:
        step += 1
        _install_addon(addon_id, name, dialog, int(step / total * 100))
        if dialog.iscanceled():
            dialog.close()
            return

    step += 1
    _configure_iptv(dialog, int(step / total * 100))

    dialog.close()
    xbmcgui.Dialog().ok(
        "Setup Complete",
        "Tony 7 Bones setup complete!\nAll add-ons installed and configured.",
    )


run()
