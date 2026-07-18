<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const activeMenu = computed(() => route.path)
const pageTitle = computed(() => String(route.meta.title ?? '工作台'))

const menuItems = [
  { path: '/', label: '工作台', mark: '首' },
  { path: '/imports', label: '数据导入', mark: '导' },
  { path: '/replenishment', label: '补库管理', mark: '补' },
  { path: '/demands', label: '生产需求', mark: '需' },
  { path: '/planning', label: '生产计划', mark: '计' },
  { path: '/execution', label: '车间执行', mark: '产' },
  { path: '/issues', label: '异常预警', mark: '异' },
  { path: '/master-data', label: '基础资料', mark: '基' },
  { path: '/system', label: '系统管理', mark: '设' },
]

function signOut() {
  auth.signOut()
  void router.replace('/login')
}

onMounted(async () => {
  try {
    await auth.loadProfile()
  } catch {
    signOut()
  }
})
</script>

<template>
  <el-container class="app-shell">
    <el-aside width="232px" class="sidebar">
      <div class="brand">
        <span class="brand-emblem">F</span>
        <div>
          <strong>福兰特</strong>
          <small>轻量生产执行系统</small>
        </div>
      </div>
      <el-menu :default-active="activeMenu" router class="main-menu">
        <el-menu-item v-for="item in menuItems" :key="item.path" :index="item.path">
          <span class="menu-mark">{{ item.mark }}</span>
          <span>{{ item.label }}</span>
        </el-menu-item>
      </el-menu>
      <div class="phase-label">PHASE 1 · FOUNDATION</div>
    </el-aside>

    <el-container>
      <el-header class="topbar">
        <div>
          <div class="eyebrow">FLANTE MANUFACTURING</div>
          <h1>{{ pageTitle }}</h1>
        </div>
        <el-dropdown trigger="click">
          <button class="user-button">
            <span class="avatar">{{ auth.user?.display_name?.slice(0, 1) ?? '用' }}</span>
            <span>{{ auth.user?.display_name ?? auth.user?.username ?? '当前用户' }}</span>
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item disabled>{{ auth.user?.roles.join(' / ') }}</el-dropdown-item>
              <el-dropdown-item divided @click="signOut">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>
      <el-main class="page-area">
        <RouterView />
      </el-main>
    </el-container>
  </el-container>
</template>
