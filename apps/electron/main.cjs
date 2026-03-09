// Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
// Developed by: Richard R. Ayuyang, PhD
// All rights reserved.

'use strict';

const { app, BrowserWindow, Menu, Tray, nativeImage, session } = require('electron');
const path = require('path');

// ── App setup ──────────────────────────────────────────────────────────────────
app.setName('RichSinkhole');

// Remove default Electron menu bar entirely
Menu.setApplicationMenu(null);

// Allow self-signed certs and HTTP for local sinkhole server
app.commandLine.appendSwitch('ignore-certificate-errors');
app.commandLine.appendSwitch('allow-insecure-localhost');

let mainWindow = null;
let tray       = null;
let isQuitting = false;

// ── Icon helpers ───────────────────────────────────────────────────────────────
function getIconBase() {
  if (app.isPackaged) {
    // asarUnpack extracts files to app.asar.unpacked/
    return path.join(process.resourcesPath, 'app.asar.unpacked', 'build');
  }
  return path.join(__dirname, '..', 'build');
}

function getLauncherIcon() {
  try {
    const p = path.join(getIconBase(), 'icons', '512x512.png');
    const img = nativeImage.createFromPath(p);
    return img.isEmpty() ? null : img;
  } catch {
    return null;
  }
}

function getTrayIcon() {
  const size = process.platform === 'linux' ? '22' : '16';
  try {
    const p = path.join(getIconBase(), `tray-${size}.png`);
    const img = nativeImage.createFromPath(p);
    if (!img.isEmpty()) return img;
  } catch { /* fall through */ }
  // Fallback to 16px
  try {
    const p = path.join(getIconBase(), 'tray-16.png');
    const img = nativeImage.createFromPath(p);
    return img.isEmpty() ? nativeImage.createEmpty() : img;
  } catch {
    return nativeImage.createEmpty();
  }
}

// ── Quit helper ────────────────────────────────────────────────────────────────
function quitApp() {
  isQuitting = true;
  if (tray) {
    tray.destroy();
    tray = null;
  }
  // Force-close all windows and quit
  BrowserWindow.getAllWindows().forEach(win => win.destroy());
  app.quit();
}

// ── Tray ───────────────────────────────────────────────────────────────────────
function createTray() {
  const icon = getTrayIcon();
  tray = new Tray(icon);
  tray.setToolTip('RichSinkhole — DNS Sinkhole Manager');

  const menu = Menu.buildFromTemplate([
    { label: 'RichSinkhole', enabled: false },
    { type: 'separator' },
    {
      label: 'Show Window',
      click() {
        if (mainWindow) {
          mainWindow.show();
          mainWindow.focus();
        }
      },
    },
    { type: 'separator' },
    {
      label: 'Quit',
      click() { quitApp(); },
    },
  ]);

  tray.setContextMenu(menu);

  // Single/double click: show window
  tray.on('click',        () => { if (mainWindow) { mainWindow.show(); mainWindow.focus(); } });
  tray.on('double-click', () => { if (mainWindow) { mainWindow.show(); mainWindow.focus(); } });
}

// ── Main window ────────────────────────────────────────────────────────────────
function createWindow() {
  const iconImg = getLauncherIcon();

  mainWindow = new BrowserWindow({
    width:       1280,
    height:      820,
    minWidth:    960,
    minHeight:   640,
    maximizable: false,
    backgroundColor: '#0d1117',
    title: 'RichSinkhole',
    ...(iconImg ? { icon: iconImg } : {}),
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,         // Required: lets renderer fetch any HTTP URL
      webSecurity: false,     // Required: bypasses CORS for local server connections
      allowRunningInsecureContent: true,
    },
    show: false,
  });

  // Override CSP so renderer can reach any user-configured server URL
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        'Content-Security-Policy': [
          "default-src 'self' 'unsafe-inline' data:; connect-src *; img-src * data:;",
        ],
      },
    });
  });

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
    mainWindow.focus();
  });

  // Intercept close → minimize to tray instead (unless quitting)
  mainWindow.on('close', (event) => {
    if (!isQuitting) {
      event.preventDefault();
      mainWindow.hide();
      // Show notification only once (Windows supports balloons)
      if (tray && process.platform === 'win32') {
        tray.displayBalloon({
          iconType: 'info',
          title: 'RichSinkhole',
          content: 'Minimized to tray. Right-click the icon to quit.',
        });
      }
    }
  });

  // Handle the window being destroyed (e.g., by OS)
  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  mainWindow.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));

  return mainWindow;
}

// ── Lifecycle ──────────────────────────────────────────────────────────────────
app.whenReady().then(() => {
  createTray();
  createWindow();

  app.on('activate', () => {
    if (mainWindow) {
      mainWindow.show();
      mainWindow.focus();
    } else {
      createWindow();
    }
  });
});

app.on('before-quit', () => {
  isQuitting = true;
});

// On Linux/Windows: keep the process alive when windows are closed (tray keeps it running)
// On macOS: quit normally
app.on('window-all-closed', () => {
  if (process.platform === 'darwin') {
    app.quit();
  }
  // Linux/Windows: intentionally do nothing — tray keeps the app alive
});
