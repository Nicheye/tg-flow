import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from './contexts/AuthContext'
import { ProtectedRoute, PublicRoute } from './components/ProtectedRoute'
import { WorkspaceShell } from './components/WorkspaceShell'
import HomePage from './pages/HomePage'
import MentionsPage from './pages/MentionsPage'
import MentionContextPage from './pages/MentionContextPage'
import LoginPage from './pages/LoginPage'
import ChatsPage from './pages/ChatsPage'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60, // 1 minute
      retry: 1,
    },
  },
})

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <WorkspaceShell>
            <Routes>
              <Route path="/" element={<HomePage />} />
              <Route
                path="/mentions"
                element={
                  <ProtectedRoute>
                    <MentionsPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/mentions/:mentionId"
                element={
                  <ProtectedRoute>
                    <MentionContextPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/chats"
                element={
                  <ProtectedRoute>
                    <ChatsPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/login"
                element={
                  <PublicRoute>
                    <LoginPage />
                  </PublicRoute>
                }
              />
            </Routes>
          </WorkspaceShell>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
