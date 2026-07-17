<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { getHealth, type HealthStatus } from '../api/health'

const health = ref<HealthStatus | null>(null)
const healthError = ref(false)

onMounted(async () => {
  try {
    health.value = await getHealth()
  } catch {
    healthError.value = true
  }
})
</script>

<template>
  <section>
    <div class="welcome-card">
      <div>
        <p class="eyebrow">SYSTEM FOUNDATION</p>
        <h2>项目基础框架已就绪</h2>
        <p>当前阶段仅包含身份验证、权限与审计基础、页面框架和服务健康检查。</p>
      </div>
      <div class="health-badge" :class="{ danger: healthError }">
        <span class="health-dot" />
        {{ healthError ? '服务连接异常' : health ? '服务运行正常' : '正在检查服务' }}
      </div>
    </div>
    <div class="foundation-grid">
      <article>
        <span>01</span>
        <h3>身份与权限</h3>
        <p>JWT 登录、角色、权限及数据审计基础表。</p>
      </article>
      <article>
        <span>02</span>
        <h3>应用骨架</h3>
        <p>Vue 3 前端与 FastAPI 后端已形成清晰边界。</p>
      </article>
      <article>
        <span>03</span>
        <h3>数据库</h3>
        <p>{{ health?.database === 'ok' ? '数据库连接正常。' : '等待数据库状态。' }}</p>
      </article>
    </div>
  </section>
</template>
