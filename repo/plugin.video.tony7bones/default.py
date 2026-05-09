import sys
import xbmcgui
import xbmcplugin

HANDLE = int(sys.argv[1])

ITEMS = [
    ("Example Video", "https://example.com/video.mp4"),
]


def list_items():
    for title, url in ITEMS:
        li = xbmcgui.ListItem(title)
        li.setInfo("video", {"title": title, "mediatype": "video"})
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=url, listitem=li)
    xbmcplugin.endOfDirectory(HANDLE)


list_items()
