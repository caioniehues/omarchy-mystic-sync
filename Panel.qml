import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons

// Mystic Sync — bar icon tinted with the live RGB colour; the panel picks what each ARGB header follows.
// The colour loop runs in the mystic-sync.service user daemon (bin/mystic-sync); this panel only reads its
// state file and writes settings through "mystic-sync set", so lighting keeps working if the shell restarts.
// IPC: omarchy-shell caioniehues.mystic-sync open|close|toggle
Panel {
  id: root
  moduleName: "caioniehues.mystic-sync"
  ipcTarget: "caioniehues.mystic-sync"
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  readonly property string pluginDir: decodeURIComponent(String(Qt.resolvedUrl(".")).replace(/^file:\/\//, "")).replace(/\/$/, "")
  readonly property string cli: pluginDir + "/bin/mystic-sync"
  readonly property string statePath: Quickshell.env("XDG_RUNTIME_DIR") + "/mystic-sync/state.json"

  property var st: null              // parsed state.json, null when the daemon has never run
  property bool stale: true          // state not refreshed recently: daemon stopped or hung
  readonly property bool live: st !== null && st.running === true && !stale
  readonly property var zoneNames: st && st.zones ? Object.keys(st.zones) : []

  readonly property var tempSources: [
    { value: "cpu-temp", label: "CPU °C" }, { value: "gpu-temp", label: "GPU °C" },
    { value: "hottest", label: "Hottest", tooltip: "Whichever of CPU/GPU is closer to its limit" },
    { value: "off", label: "Off" }
  ]
  readonly property var loadSources: [
    { value: "cpu-load", label: "CPU load" }, { value: "gpu-load", label: "GPU load" },
    { value: "busiest", label: "Busiest", tooltip: "Whichever of CPU/GPU is busier" }
  ]
  readonly property var palettes: [
    { value: "thermal", label: "Thermal" }, { value: "ice-fire", label: "Ice → fire" }, { value: "traffic", label: "Traffic" }, { value: "violet", label: "Violet" }
  ]

  function set(pairs) { Quickshell.execDetached([root.cli, "set"].concat(pairs)) }
  function fmt(v, unit) { return v === null || v === undefined ? "—" : Math.round(v) + (unit === "%" ? "%" : "°") }

  FileView {
    id: stateFile
    path: root.statePath
    printErrors: false
    onLoaded: {
      try {
        root.st = JSON.parse(text())
        root.stale = (Date.now() / 1000 - (root.st.updated || 0)) > 10
      } catch (e) { root.stale = true }
    }
    onLoadFailed: { root.st = null; root.stale = true }
  }

  Timer {
    interval: root.opened ? 500 : 2000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: stateFile.reload()
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "󰌵"
    foreground: root.live && root.st.enabled && root.st.accent ? root.st.accent : root.barForeground
    onPressed: function(b) { if (b === Qt.RightButton) root.set(["enabled=" + !(root.st && root.st.enabled)]); else root.toggle() }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(440))
    contentHeight: panel.fittedContentHeight(panelColumn.implicitHeight, Style.space(760))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      ScrollView {
        id: scrollArea
        anchors.fill: parent
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

        Column {
          id: panelColumn
          width: scrollArea.availableWidth
          spacing: Style.space(14)

          PanelHero {
            width: parent.width
            title: "Mystic Sync"
            meta: {
              if (!root.live) return root.st === null ? "SERVICE NOT RUNNING" : "SERVICE STOPPED"
              var m = root.st.metrics || {}
              return "CPU " + root.fmt(m["cpu-temp"]) + " " + root.fmt(m["cpu-load"], "%")
                + " · GPU " + root.fmt(m["gpu-temp"]) + " " + root.fmt(m["gpu-load"], "%")
                + (root.st.critical ? " · CRITICAL" : "")
            }
            foreground: root.bar.foreground
            fontFamily: root.bar.fontFamily
            iconComponent: Component {
              Text {
                text: "󰌵"
                color: button.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.display
              }
            }
            trailingControl: Component {
              ToggleSwitch {
                visible: root.live
                checked: root.st ? root.st.enabled === true : false
                foreground: root.bar.foreground
                onToggled: root.set(["enabled=" + !checked])
              }
            }
          }

          PlainNote {
            visible: !root.live || (root.st && root.st.error)
            color: root.bar.urgent
            text: !root.live ? "Start it with: systemctl --user enable --now mystic-sync" : (root.st.error || "")
          }

          PlainNote {
            visible: root.live && root.st.enabled === false
            text: "Paused: your previous OpenRGB lighting is restored."
          }

          Repeater {
            model: root.zoneNames

            Column {
              id: zoneCol
              required property string modelData
              readonly property var zone: root.st.zones[modelData]
              width: panelColumn.width
              spacing: Style.space(8)

              PanelSeparator { foreground: root.bar.foreground }

              PanelSectionHeader {
                text: zoneCol.modelData + " · " + String(zoneCol.zone.label).toUpperCase()
                foreground: root.bar.foreground
                fontFamily: root.bar.fontFamily
              }

              Row {
                spacing: Style.space(10)
                Rectangle {
                  width: Style.space(28); height: Style.space(28)
                  radius: Style.cornerRadius > 0 ? Style.space(6) : 0
                  color: zoneCol.zone.color
                  border.width: 1
                  border.color: Qt.darker(root.bar.foreground, 2)
                }
                PlainNote {
                  anchors.verticalCenter: parent.verticalCenter
                  width: undefined
                  color: root.bar.foreground
                  text: zoneCol.zone.source === "off" ? "Off"
                    : root.fmt(zoneCol.zone.value, zoneCol.zone.unit) + "  ·  " + Math.round((zoneCol.zone.level || 0) * 100) + "% of range"
                }
              }

              ButtonGroup {
                options: root.tempSources
                value: zoneCol.zone.source
                foreground: root.bar.foreground
                background: root.bar.background
                fontFamily: root.bar.fontFamily
                onChanged: function(v) { root.set(["zones." + zoneCol.modelData + ".source=" + v]) }
              }
              ButtonGroup {
                options: root.loadSources
                value: zoneCol.zone.source
                foreground: root.bar.foreground
                background: root.bar.background
                fontFamily: root.bar.fontFamily
                onChanged: function(v) { root.set(["zones." + zoneCol.modelData + ".source=" + v]) }
              }
            }
          }

          PanelSeparator { visible: root.live; foreground: root.bar.foreground }

          Column {
            visible: root.live
            width: parent.width
            spacing: Style.space(8)

            PanelSectionHeader { text: "PALETTE"; foreground: root.bar.foreground; fontFamily: root.bar.fontFamily }
            ButtonGroup {
              options: root.palettes
              value: root.st ? root.st.palette : ""
              foreground: root.bar.foreground
              background: root.bar.background
              fontFamily: root.bar.fontFamily
              onChanged: function(v) { root.set(["palette=" + v]) }
            }

            PanelSectionHeader { text: "BRIGHTNESS"; foreground: root.bar.foreground; fontFamily: root.bar.fontFamily }
            Item {
              width: parent.width
              height: Style.space(28)
              PanelSlider {
                anchors.fill: parent
                bar: root.bar
                minimum: 5
                maximum: 100
                step: 5
                integer: true
                value: root.st ? root.st.brightness : 100
                onReleased: function(v) { root.set(["brightness=" + Math.round(v)]) }
              }
            }
          }

          Text {
            width: parent.width
            text: "right-click icon pauses · config: ~/.config/mystic-sync/config.json"
            textFormat: Text.PlainText
            color: Qt.darker(root.bar.foreground, 1.8)
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
          }
        }
      }
    }
  }

  component PlainNote: Text {
    width: panelColumn.width
    textFormat: Text.PlainText
    wrapMode: Text.Wrap
    color: Qt.darker(root.bar.foreground, 1.4)
    font.family: root.bar.fontFamily
    font.pixelSize: Style.font.body
  }
}
