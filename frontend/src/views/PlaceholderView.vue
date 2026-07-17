<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const title = computed(() => String(route.meta.title ?? '功能页面'))
</script>

<template>
  <section class="placeholder-card">
    <span class="placeholder-index">PHASE 1</span>
    <h2>{{ title }}</h2>
    <p>页面路由已建立，业务功能将在对应阶段通过验收后开发。</p>
    <el-tag effect="plain">当前为空白页面</el-tag>
  </section>
</template>
