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
  readonly property var paletteLabels: ({ "thermal": "Thermal", "ice-fire": "Ice → fire", "traffic": "Traffic", "violet": "Violet" })
  readonly property var paletteOptions: st && st.palettes
    ? Object.keys(st.palettes).map(function(n) { return { value: n, label: root.paletteLabels[n] || n } }) : []
  // Colours that look the same on both fan models (README, "Mixed fan models render colours differently")
  readonly property var matchedColors: ["#ff0000", "#00ff00", "#0000ff", "#5a00ff", "#b400ff", "#ff00ff"]

  // ---- palette composer: edits a copy; Save writes it through the CLI, which validates ----
  property string cName: ""
  property var cStops: []            // [{ pos: 0..1, color: "#rrggbb" }], first at 0, last at 1
  property int cSel: -1              // selected stop; while >= 0 it is previewed on cZone
  property string cZone: ""
  property string cError: ""
  property bool composing: false     // the panel shows the composer instead of the zones
  readonly property bool cMiddle: cSel > 0 && cSel < cStops.length - 1
  // Stops are stored 0..1 and shown in the units of the previewed zone's source (a palette fits any range).
  // hottest/busiest mix two ranges, so they and "off" fall back to percent of range.
  readonly property string cSource: st && st.zones && st.zones[cZone] ? st.zones[cZone].source : ""
  readonly property var cRange: st && st.ranges && st.ranges[cSource] ? st.ranges[cSource] : null
  readonly property var cSpan: cRange || [0, 100]
  readonly property string cUnit: cRange ? (cSource.indexOf("temp") >= 0 ? " °C" : "%") : "% of range"
  function toUnit(p) { return root.cSpan[0] + p * (root.cSpan[1] - root.cSpan[0]) }
  function fromUnit(v) { return Math.round((v - root.cSpan[0]) / (root.cSpan[1] - root.cSpan[0]) * 1000) / 1000 }
  function posLabel(p) { return Math.round(root.toUnit(p)) + root.cUnit }
  readonly property var previewZones: st && st.zones
    ? Object.keys(st.zones).filter(function(n) { return st.zones[n].source !== "off" })
        .map(function(n) { return { value: n, label: st.zones[n].label } }) : []

  function set(pairs) { Quickshell.execDetached([root.cli, "set"].concat(pairs)) }
  function run(pairs) { root.cError = ""; cliProc.command = [root.cli, "set"].concat(pairs); cliProc.running = true }

  function hex(r, g, b) {
    return "#" + [r, g, b].map(function(v) { return ("0" + Math.max(0, Math.min(255, Math.round(v))).toString(16)).slice(-2) }).join("")
  }
  function channel(h, i) { return parseInt(h.substr(1 + 2 * i, 2), 16) }
  function sample(t) {                 // same interpolation as mysticlib.palette_color
    var s = root.cStops
    if (!s.length) return "#000000"
    for (var i = 1; i < s.length; i++) {
      if (t <= s[i].pos) {
        var a = s[i - 1], b = s[i], f = b.pos === a.pos ? 0 : (t - a.pos) / (b.pos - a.pos)
        function mix(k) { return root.channel(a.color, k) + (root.channel(b.color, k) - root.channel(a.color, k)) * f }
        return root.hex(mix(0), mix(1), mix(2))
      }
    }
    return s[s.length - 1].color
  }
  function loadPalette(n) {
    if (!st || !st.palettes || !st.palettes[n]) return
    root.cStops = st.palettes[n].map(function(s) { return { pos: s[0], color: s[1] } })
    root.cName = st.builtin.indexOf(n) >= 0 ? n + "-2" : n
    root.cSel = -1
    root.cError = ""
    root.pushPreview()
  }
  function select(i) { root.cSel = root.cSel === i ? -1 : i; root.pushPreview() }
  function editStop(i, change) {
    var s = root.cStops.slice()
    s[i] = Object.assign({}, s[i], change)
    root.cStops = s
    root.pushPreview()
  }
  function setChannel(ch, v) {
    var c = [0, 1, 2].map(function(k) { return root.channel(root.cStops[root.cSel].color, k) })
    c[ch] = v
    root.editStop(root.cSel, { color: root.hex(c[0], c[1], c[2]) })
  }
  function addStop() {                 // split the widest gap, starting with the colour already there
    var s = root.cStops, i = 0
    for (var k = 1; k < s.length - 1; k++) if (s[k + 1].pos - s[k].pos > s[i + 1].pos - s[i].pos) i = k
    var p = Math.round((s[i].pos + s[i + 1].pos) * 500) / 1000
    var next = s.slice()
    next.splice(i + 1, 0, { pos: p, color: root.sample(p) })
    root.cStops = next
    root.cSel = i + 1
    root.pushPreview()
  }
  function removeStop() {
    var s = root.cStops.slice()
    s.splice(root.cSel, 1)
    root.cStops = s
    root.cSel = -1
    root.pushPreview()
  }
  function save() {
    if (!/^[a-z0-9-]+$/.test(root.cName) || st.builtin.indexOf(root.cName) >= 0) {
      root.cError = "Name: lowercase letters, digits and -, and not a built-in name."
      return
    }
    root.run(["palettes." + root.cName + "=" + JSON.stringify(root.cStops.map(function(s) { return [Math.round(s.pos * 1000) / 1000, s.color] }))])
  }
  function pushPreview() {
    previewFile.setText(root.opened && root.cSel >= 0 && root.cZone && root.cStops[root.cSel]
      ? JSON.stringify({ zone: root.cZone, color: root.cStops[root.cSel].color }) : "{}")
  }
  onOpenedChanged: if (!opened) { root.composing = false; root.cSel = -1; root.pushPreview() }
  function closeComposer() { root.composing = false; root.cSel = -1; root.pushPreview() }

  FileView {
    id: previewFile
    path: Quickshell.env("XDG_RUNTIME_DIR") + "/mystic-sync/preview.json"
    atomicWrites: true
    printErrors: false
  }
  Timer {                              // the daemon drops a preview older than 3 s, so keep it fresh
    interval: 1000
    running: root.opened && root.cSel >= 0
    repeat: true
    onTriggered: root.pushPreview()
  }
  Process {
    id: cliProc
    stderr: StdioCollector { onStreamFinished: if (text.trim()) root.cError = text.trim() }
  }
  function fmt(v, unit) { return v === null || v === undefined ? "—" : Math.round(v) + (unit === "%" ? "%" : "°") }

  FileView {
    id: stateFile
    path: root.statePath
    printErrors: false
    onLoaded: {
      try {
        root.st = JSON.parse(text())
        root.stale = (Date.now() / 1000 - (root.st.updated || 0)) > 10
        if (!root.cStops.length && root.st.palettes) root.loadPalette(root.st.palette)
        if (!root.cZone && root.previewZones.length) root.cZone = root.previewZones[0].value
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
              visible: !root.composing
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
              Dropdown {
                width: parent.width
                label: "Palette"
                value: zoneCol.zone.palette || ""
                options: [{ value: "", label: "Default (" + (root.paletteLabels[root.st.palette] || root.st.palette) + ")" }].concat(root.paletteOptions)
                foreground: root.bar.foreground
                background: root.bar.background
                fontFamily: root.bar.fontFamily
                onChanged: function(v) { root.set(["zones." + zoneCol.modelData + ".palette=" + (v === "" ? "null" : v)]) }
              }
            }
          }

          PanelSeparator { visible: root.live && !root.composing; foreground: root.bar.foreground }

          Column {
            visible: root.live && !root.composing
            width: parent.width
            spacing: Style.space(8)

            PanelSectionHeader { text: "DEFAULT PALETTE"; foreground: root.bar.foreground; fontFamily: root.bar.fontFamily }
            Dropdown {
              width: parent.width
              showLabel: false
              options: root.paletteOptions
              value: root.st ? root.st.palette : ""
              foreground: root.bar.foreground
              background: root.bar.background
              fontFamily: root.bar.fontFamily
              onChanged: function(v) { root.set(["palette=" + v]) }
            }
            Button { text: "Compose palette…"; bordered: true; foreground: root.bar.foreground; fontFamily: root.bar.fontFamily; onClicked: root.composing = true }

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

          Column {
            id: composer
            visible: root.live && root.composing && root.cStops.length > 0
            width: parent.width
            spacing: Style.space(8)

            Button { text: "← Back"; bordered: true; foreground: root.bar.foreground; fontFamily: root.bar.fontFamily; onClicked: root.closeComposer() }
            PanelSectionHeader { text: "COMPOSE PALETTE"; foreground: root.bar.foreground; fontFamily: root.bar.fontFamily }
            Dropdown {
              width: parent.width
              label: "Start from"
              value: root.st && root.st.palettes && root.st.palettes[root.cName] ? root.cName : ""
              options: root.paletteOptions
              foreground: root.bar.foreground
              background: root.bar.background
              fontFamily: root.bar.fontFamily
              onChanged: function(v) { root.loadPalette(v) }
            }
            TextField {
              width: parent.width
              text: root.cName
              placeholderText: "palette name"
              foreground: root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.body
              onTextEdited: root.cName = text
            }

            Row {                        // the palette as the lights would sweep through it
              width: parent.width
              height: Style.space(22)
              Repeater {
                model: 64
                Rectangle {
                  required property int index
                  width: composer.width / 64
                  height: parent.height
                  color: root.sample(index / 63)
                }
              }
            }
            Item {                       // the range ends, in the previewed zone's units
              width: parent.width
              height: lowText.implicitHeight
              Text { id: lowText; text: root.posLabel(0); color: Qt.darker(root.bar.foreground, 1.4); font.family: root.bar.fontFamily; font.pixelSize: Style.font.caption }
              Text { anchors.right: parent.right; text: root.posLabel(1); color: Qt.darker(root.bar.foreground, 1.4); font.family: root.bar.fontFamily; font.pixelSize: Style.font.caption }
            }
            Item {                       // stops: click one to edit it and preview it on the lights
              width: parent.width
              height: Style.space(26)
              Repeater {
                model: root.cStops
                Rectangle {
                  required property var modelData
                  required property int index
                  x: modelData.pos * (parent.width - width)
                  width: Style.space(22); height: Style.space(22)
                  radius: Style.cornerRadius > 0 ? Style.space(4) : 0
                  color: modelData.color
                  border.width: index === root.cSel ? 3 : 1
                  border.color: index === root.cSel ? root.bar.foreground : Qt.darker(root.bar.foreground, 2)
                  MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.select(parent.index) }
                }
              }
            }

            Column {
              visible: root.cSel >= 0 && root.cSel < root.cStops.length
              width: parent.width
              spacing: Style.space(6)
              readonly property var stop: visible ? root.cStops[root.cSel] : ({ pos: 0, color: "#000000" })

              PlainNote {
                text: "Stop " + (root.cSel + 1) + " at " + root.posLabel(parent.stop.pos) + ", shown on the lights while selected"
              }
              ButtonGroup {
                options: root.previewZones
                value: root.cZone
                foreground: root.bar.foreground
                background: root.bar.background
                fontFamily: root.bar.fontFamily
                onChanged: function(v) { root.cZone = v; root.pushPreview() }
              }
              Row {
                visible: root.cMiddle
                spacing: Style.space(8)
                Text { width: Style.space(36); text: "Pos"; color: root.bar.foreground; font.family: root.bar.fontFamily; font.pixelSize: Style.font.body; anchors.verticalCenter: parent.verticalCenter }
                PanelSlider {
                  width: composer.width - Style.space(44)
                  height: Style.space(28)
                  bar: root.bar
                  minimum: root.cMiddle ? Math.ceil(root.toUnit(root.cStops[root.cSel - 1].pos)) + 1 : root.cSpan[0]
                  maximum: root.cMiddle ? Math.floor(root.toUnit(root.cStops[root.cSel + 1].pos)) - 1 : root.cSpan[1]
                  step: 1
                  integer: true
                  value: root.cMiddle ? root.toUnit(root.cStops[root.cSel].pos) : 0
                  onMoved: function(v) { root.editStop(root.cSel, { pos: root.fromUnit(v) }) }
                }
              }
              Repeater {
                model: ["R", "G", "B"]
                Row {
                  required property string modelData
                  required property int index
                  spacing: Style.space(8)
                  Text { width: Style.space(36); text: parent.modelData; color: root.bar.foreground; font.family: root.bar.fontFamily; font.pixelSize: Style.font.body; anchors.verticalCenter: parent.verticalCenter }
                  PanelSlider {
                    width: composer.width - Style.space(44)
                    height: Style.space(28)
                    bar: root.bar
                    minimum: 0
                    maximum: 255
                    step: 1
                    integer: true
                    value: root.cSel >= 0 && root.cStops[root.cSel] ? root.channel(root.cStops[root.cSel].color, parent.index) : 0
                    onMoved: function(v) { root.setChannel(parent.index, v) }
                  }
                }
              }
              Row {
                spacing: Style.space(6)
                TextField {
                  width: Style.space(110)
                  text: parent.parent.stop.color
                  foreground: root.bar.foreground
                  font.family: root.bar.fontFamily
                  font.pixelSize: Style.font.body
                  onAccepted: if (/^#[0-9a-fA-F]{6}$/.test(text)) root.editStop(root.cSel, { color: text.toLowerCase() })
                }
                Repeater {               // known to match on both fan models
                  model: root.matchedColors
                  Rectangle {
                    required property string modelData
                    anchors.verticalCenter: parent.verticalCenter
                    width: Style.space(22); height: Style.space(22)
                    radius: Style.cornerRadius > 0 ? Style.space(4) : 0
                    color: modelData
                    border.width: 1
                    border.color: Qt.darker(root.bar.foreground, 2)
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.editStop(root.cSel, { color: parent.modelData }) }
                  }
                }
              }
            }

            Flow {                       // range of the previewed zone's source; shared by every zone on that source
              visible: root.cRange !== null
              width: parent.width
              spacing: Style.space(12)
              NumberField {
                label: "Low"
                from: 0
                to: root.cRange ? root.cRange[1] - 1 : 100
                value: root.cRange ? root.cRange[0] : 0
                foreground: root.bar.foreground
                fontFamily: root.bar.fontFamily
                onModified: function(v) { root.run(["ranges." + root.cSource + "=" + JSON.stringify([v, root.cRange[1]])]) }
              }
              NumberField {
                label: "High"
                from: root.cRange ? root.cRange[0] + 1 : 1
                to: root.cSource.indexOf("temp") >= 0 ? 125 : 100
                value: root.cRange ? root.cRange[1] : 100
                foreground: root.bar.foreground
                fontFamily: root.bar.fontFamily
                onModified: function(v) { root.run(["ranges." + root.cSource + "=" + JSON.stringify([root.cRange[0], v])]) }
              }
            }
            PlainNote {
              visible: root.cRange === null && root.cSel >= 0
              text: "Hottest and Busiest use each reading's own range, so positions show as a percentage."
            }

            Flow {
              width: parent.width
              spacing: Style.space(6)
              Button { text: "Add stop"; enabled: root.cStops.length < 8; bordered: true; foreground: root.bar.foreground; fontFamily: root.bar.fontFamily; onClicked: root.addStop() }
              Button { text: "Remove stop"; enabled: root.cMiddle && root.cStops.length > 2; bordered: true; foreground: root.bar.foreground; fontFamily: root.bar.fontFamily; onClicked: root.removeStop() }
              Button { text: "Save"; bordered: true; foreground: root.bar.foreground; fontFamily: root.bar.fontFamily; onClicked: root.save() }
              Button {
                text: "Delete"
                visible: root.st && root.st.palettes && root.st.palettes[root.cName] !== undefined && root.st.builtin.indexOf(root.cName) < 0
                bordered: true
                foreground: root.bar.foreground
                fontFamily: root.bar.fontFamily
                onClicked: root.run(["palettes." + root.cName + "=null"])
              }
            }
            PlainNote { visible: root.cError !== ""; color: root.bar.urgent; text: root.cError }
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
