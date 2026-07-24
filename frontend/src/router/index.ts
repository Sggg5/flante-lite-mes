import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import MainLayout from '../layouts/MainLayout.vue'
import DashboardView from '../views/DashboardView.vue'
import LoginView from '../views/LoginView.vue'
import ImportCenterView from '../views/ImportCenterView.vue'
import ProductionDemandView from '../views/ProductionDemandView.vue'
import ReplenishmentView from '../views/ReplenishmentView.vue'
import PlaceholderView from '../views/PlaceholderView.vue'
import { TOKEN_STORAGE_KEY } from '../api/http'

const placeholderRoutes: RouteRecordRaw[] = [
  { path: 'imports', name: 'imports', component: ImportCenterView, meta: { title: '数据导入' } },
  { path: 'replenishment', name: 'replenishment', component: ReplenishmentView, meta: { title: '补库管理' } },
  { path: 'demands', name: 'demands', component: ProductionDemandView, meta: { title: '生产需求' } },
  { path: 'planning', name: 'planning', component: PlaceholderView, meta: { title: '生产计划' } },
  { path: 'execution', name: 'execution', component: PlaceholderView, meta: { title: '车间执行' } },
  { path: 'issues', name: 'issues', component: PlaceholderView, meta: { title: '异常预警' } },
  { path: 'master-data', name: 'master-data', component: PlaceholderView, meta: { title: '基础资料' } },
  { path: 'system', name: 'system', component: PlaceholderView, meta: { title: '系统管理' } },
]

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: LoginView, meta: { public: true, title: '登录' } },
    {
      path: '/',
      component: MainLayout,
      children: [
        { path: '', name: 'dashboard', component: DashboardView, meta: { title: '工作台' } },
        ...placeholderRoutes,
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach((to) => {
  const authenticated = Boolean(localStorage.getItem(TOKEN_STORAGE_KEY))
  if (!to.meta.public && !authenticated) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && authenticated) {
    return { name: 'dashboard' }
  }
  document.title = `${String(to.meta.title ?? '系统')} - 福兰特轻量MES`
  return true
})

export default router
