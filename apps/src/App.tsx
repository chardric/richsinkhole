// Copyright (c) 2026 DownStreamTech (https://downstreamtech.net)
// All rights reserved.

import { HashRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './context/AuthContext'
import { ToastProvider } from './context/ToastContext'
import { Layout } from './components/Layout'
import { ToastContainer } from './components/Toast'
import { SetupScreen }     from './screens/SetupScreen'
import { DashboardScreen } from './screens/DashboardScreen'
import { LogsScreen }      from './screens/LogsScreen'
import { BlocklistScreen } from './screens/BlocklistScreen'
import { DevicesScreen }   from './screens/DevicesScreen'
import { SecurityScreen }  from './screens/SecurityScreen'
import { SchedulesScreen } from './screens/SchedulesScreen'
import { PrivacyScreen }   from './screens/PrivacyScreen'
import { ProxyScreen }     from './screens/ProxyScreen'
import { SettingsScreen }  from './screens/SettingsScreen'

function AuthGate() {
  const { isAuthenticated } = useAuth()

  if (!isAuthenticated) {
    return (
      <Routes>
        <Route path="/setup"  element={<SetupScreen />} />
        <Route path="*"       element={<Navigate to="/setup" replace />} />
      </Routes>
    )
  }

  return (
    <Layout>
      <Routes>
        <Route path="/dashboard"  element={<DashboardScreen />} />
        <Route path="/logs"       element={<LogsScreen />} />
        <Route path="/blocklist"  element={<BlocklistScreen />} />
        <Route path="/devices"    element={<DevicesScreen />} />
        <Route path="/security"   element={<SecurityScreen />} />
        <Route path="/schedules"  element={<SchedulesScreen />} />
        <Route path="/privacy"    element={<PrivacyScreen />} />
        <Route path="/proxy"      element={<ProxyScreen />} />
        <Route path="/settings"   element={<SettingsScreen />} />
        <Route path="/more"       element={<></>} />
        <Route path="*"          element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </Layout>
  )
}

export default function App() {
  return (
    <HashRouter>
      <AuthProvider>
        <ToastProvider>
          <AuthGate />
          <ToastContainer />
        </ToastProvider>
      </AuthProvider>
    </HashRouter>
  )
}
