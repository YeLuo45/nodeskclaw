import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { getCurrentLocale } from '@/i18n'
import { resolveApiErrorMessage } from '@/i18n/error'
import { useToast } from '@/composables/useToast'
import { i18n } from '@/i18n'

let lastBackendWarningAt = 0
const BACKEND_WARNING_COOLDOWN = 15_000
let lastUnsupportedCapabilityAt = 0
const UNSUPPORTED_CAPABILITY_COOLDOWN = 3000

function notifyBackendUnavailable(status?: number) {
  const now = Date.now()
  if (now - lastBackendWarningAt < BACKEND_WARNING_COOLDOWN) return
  lastBackendWarningAt = now

  const { t } = i18n.global
  const toast = useToast()
  const key =
    status && status >= 502 && status <= 504
      ? 'errors.system.backend_starting'
      : 'errors.system.backend_unreachable'
  toast.warning(t(key), { duration: 6000 })
}

function notifyUnsupportedCapability(error: AxiosError) {
  const data = error.response?.data as any
  const isUnsupported =
    data?.details?.code === 'UNSUPPORTED_CAPABILITY'
    || data?.message_key === 'errors.runtime.unsupported_capability'
  if (!isUnsupported) return

  const now = Date.now()
  if (now - lastUnsupportedCapabilityAt < UNSUPPORTED_CAPABILITY_COOLDOWN) return
  lastUnsupportedCapabilityAt = now

  const toast = useToast()
  toast.warning(resolveApiErrorMessage(error), { duration: 5000 })
}

const TOKEN_KEY = 'portal_token'
const REFRESH_KEY = 'portal_refresh_token'

let isRefreshing = false
let pendingQueue: Array<{
  resolve: (token: string) => void
  reject: (err: unknown) => void
}> = []

function clearTokensAndRedirect() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(REFRESH_KEY)
  import('@/stores/auth').then(({ useAuthStore }) => useAuthStore().clearAuth())
  if (window.location.pathname !== '/login') {
    import('@/router').then(({ default: router }) => router.push('/login'))
  }
}

async function handleTokenRefresh(failedConfig: InternalAxiosRequestConfig) {
  const refreshToken = localStorage.getItem(REFRESH_KEY)
  if (!refreshToken) {
    clearTokensAndRedirect()
    return Promise.reject(new Error('no refresh token'))
  }

  if (isRefreshing) {
    return new Promise<string>((resolve, reject) => {
      pendingQueue.push({ resolve, reject })
    }).then((newToken) => {
      failedConfig.headers.Authorization = `Bearer ${newToken}`
      return api(failedConfig)
    })
  }

  isRefreshing = true
  try {
    const res = await axios.post('/api/v1/auth/refresh', { refresh_token: refreshToken })
    const { access_token, refresh_token: newRefresh } = res.data.data

    localStorage.setItem(TOKEN_KEY, access_token)
    localStorage.setItem(REFRESH_KEY, newRefresh)
    const { useAuthStore } = await import('@/stores/auth')
    useAuthStore().setTokens(access_token, newRefresh)

    pendingQueue.forEach((p) => p.resolve(access_token))
    pendingQueue = []

    failedConfig.headers.Authorization = `Bearer ${access_token}`
    return api(failedConfig)
  } catch {
    pendingQueue.forEach((p) => p.reject(new Error('refresh failed')))
    pendingQueue = []
    clearTokensAndRedirect()
    return Promise.reject(new Error('refresh failed'))
  } finally {
    isRefreshing = false
  }
}

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  config.headers['Accept-Language'] = getCurrentLocale()
  return config
})

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const status = error.response?.status

    if (!error.response || error.code === 'ERR_NETWORK' || error.code === 'ECONNABORTED') {
      notifyBackendUnavailable()
    } else if (status && status >= 502 && status <= 504) {
      notifyBackendUnavailable(status)
    }

    if (status === 401 && error.config) {
      const hasAuth = !!error.config.headers?.Authorization
      const url = String(error.config.url ?? '')
      const isRefreshUrl = url.includes('/auth/refresh')

      if (hasAuth && !isRefreshUrl && !(error.config as any)._retried) {
        (error.config as any)._retried = true
        return handleTokenRefresh(error.config)
      }

      if (!hasAuth || isRefreshUrl) {
        clearTokensAndRedirect()
      }
    }

    if (status === 403) {
      const detail = error.response?.data as any
      if (detail?.detail?.error_code === 40350 && window.location.pathname !== '/force-change-password') {
        import('@/router').then(({ default: router }) => router.push('/force-change-password'))
      }
    }

    notifyUnsupportedCapability(error)

    return Promise.reject(error)
  },
)

export default api
