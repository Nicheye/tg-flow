const defaultApiUrl = import.meta.env.DEV ? 'http://localhost:8081' : ''

export const API_URL = (import.meta.env.VITE_API_URL || defaultApiUrl).replace(/\/+$/, '')
export const AUTH_API_URL = (import.meta.env.VITE_AUTH_API_URL || `${API_URL}/api/auth`).replace(/\/+$/, '')
