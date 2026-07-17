import axios from 'axios'

export interface HealthStatus {
  status: string
  service: string
  version: string
  database: string
}

export async function getHealth(): Promise<HealthStatus> {
  const response = await axios.get<HealthStatus>('/health', { timeout: 5000 })
  return response.data
}
