// Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
// All rights reserved.

'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electron', {
  platform: process.platform,
  versions: {
    electron: process.versions.electron,
    node: process.versions.node,
    chrome: process.versions.chrome,
  },
  // Expose safe IPC channels if needed in the future
  send: (channel, data) => {
    const allowedChannels = ['app-ready'];
    if (allowedChannels.includes(channel)) {
      ipcRenderer.send(channel, data);
    }
  },
});
