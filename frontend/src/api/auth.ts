import http from './http'

export interface LoginPayload {
  username: string
  password: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
}

export interface UserProfile {
  id: number
  username: string
  display_name: string
  roles: string[]
  permissions: string[]
}

export async function login(payload: LoginPayload): Promise<TokenResponse> {
  const response = await http.post<TokenResponse>('/v1/auth/login', payload)
  return response.data
}

export async function getCurrentUser(): Promise<UserProfile> {
  const response = await http.get<UserProfile>('/v1/auth/me')
  return response.data
}
