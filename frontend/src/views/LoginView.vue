<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { FormInstance, FormRules } from 'element-plus'
import { ElMessage } from 'element-plus'
import axios from 'axios'

import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const formRef = ref<FormInstance>()
const submitting = ref(false)
const form = reactive({ username: '', password: '' })
const rules: FormRules<typeof form> = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function submit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    await auth.signIn(form)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    await router.replace(redirect)
  } catch (error) {
    const message = axios.isAxiosError(error)
      ? (error.response?.data as { message?: string } | undefined)?.message
      : undefined
    ElMessage.error(message ?? '登录失败，请检查服务连接')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-story">
      <div class="story-content">
        <span class="story-tag">FLANTE · MES</span>
        <h1>让计划有据可查，<br />让执行清晰可见。</h1>
        <p>面向不锈钢管材、管件制造现场的轻量生产计划执行系统。</p>
        <div class="story-grid">
          <span>01<br /><small>需求不丢失</small></span>
          <span>02<br /><small>计划可追溯</small></span>
          <span>03<br /><small>执行有闭环</small></span>
        </div>
      </div>
    </section>
    <section class="login-panel">
      <div class="login-card">
        <div class="login-logo">F</div>
        <p class="eyebrow">WELCOME BACK</p>
        <h2>登录生产系统</h2>
        <p class="muted">使用管理员分配的账户继续</p>
        <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @keyup.enter="submit">
          <el-form-item label="用户名" prop="username">
            <el-input v-model="form.username" size="large" autocomplete="username" placeholder="请输入用户名" />
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input
              v-model="form.password"
              size="large"
              type="password"
              show-password
              autocomplete="current-password"
              placeholder="请输入密码"
            />
          </el-form-item>
          <el-button type="primary" size="large" :loading="submitting" class="login-submit" @click="submit">
            进入系统
          </el-button>
        </el-form>
        <p class="login-note">阶段 1 · 项目基础框架</p>
      </div>
    </section>
  </main>
</template>
